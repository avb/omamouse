from __future__ import annotations

import fcntl
import getpass
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import config, paths, tailscale


def _run(cmd: list[str], timeout: float = 4.0) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return subprocess.CompletedProcess(cmd, 127, "", "not found")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", "timeout")


def package_version() -> str | None:
    if not shutil.which("lan-mouse"):
        return None
    proc = _run(["lan-mouse", "--version"])
    text = (proc.stdout or proc.stderr).strip()
    if proc.returncode != 0:
        return "unknown"
    return text.split()[-1] if text else "unknown"


def fingerprint() -> str:
    if not paths.CERT_PATH.exists():
        return ""
    proc = _run(["openssl", "x509", "-in", str(paths.CERT_PATH), "-noout", "-fingerprint", "-sha256"])
    if proc.returncode != 0 or "=" not in proc.stdout:
        return ""
    return proc.stdout.strip().split("=", 1)[1].strip().lower()


def pid_alive() -> int | None:
    try:
        pid = int(paths.PID_PATH.read_text().strip())
        if pid <= 1:
            return None
        os.kill(pid, 0)
    except (OSError, ValueError):
        return None
    cmdline = Path(f"/proc/{pid}/cmdline")
    try:
        args = cmdline.read_bytes().split(b"\x00")
    except OSError:
        args = []
    if not args or Path(os.fsdecode(args[0])).name != "lan-mouse":
        return None
    return pid


def desired_on() -> bool:
    try:
        return paths.DESIRED_PATH.read_text().strip() == "on"
    except OSError:
        return False


def set_desired(value: str) -> None:
    paths.ensure()
    paths.atomic_write(paths.DESIRED_PATH, value + "\n")
    paths.DESIRED_PATH.chmod(0o600)


def clipboard_on() -> bool:
    try:
        return paths.CLIPBOARD_FLAG.read_text().strip() != "off"
    except OSError:
        return True


def set_clipboard_flag(enabled: bool) -> None:
    paths.ensure()
    paths.atomic_write(paths.CLIPBOARD_FLAG, ("on" if enabled else "off") + "\n")
    paths.CLIPBOARD_FLAG.chmod(0o600)


def load_config() -> dict:
    try:
        text = paths.CONFIG_PATH.read_text()
    except FileNotFoundError:
        text = ""
    return config.parse(text)


def clipboard_hook(name: str, ip: str, os_name: str) -> str:
    installed = Path.home() / ".config" / "omarchy" / "plugins" / paths.PLUGIN_ID / "scripts" / "clipboard-push"
    script = installed if installed.is_file() else paths.PUSH_SCRIPT
    return shlex.join([str(script), name, ip, os_name])


def write_config(cfg: dict) -> None:
    text = config.dumps(cfg)
    paths.ensure()
    paths.atomic_write(paths.CONFIG_PATH, text)


def restart_if_running() -> None:
    if pid_alive():
        stop_daemon(forget_desired=False)
        time.sleep(0.2)
        result = start_daemon()
        if not result.get("ok"):
            raise ValueError(result.get("error") or "Could not restart lan-mouse")


def build_status() -> dict:
    ts = tailscale.status()
    cfg = load_config()
    version = package_version()
    daemon_pid = pid_alive()
    authorized_by_name = {name: fp for fp, name in cfg["authorized_fingerprints"].items()}
    configured = {c["hostname"]: c for c in cfg["clients"] if c.get("hostname")}
    try:
        from .ssh import load_users

        ssh_users = load_users()
    except Exception:
        ssh_users = {}
    try:
        from .health import load_peer_health, local_health

        peer_health = load_peer_health()
        local = local_health() if daemon_pid else {}
    except Exception:
        peer_health = {}
        local = {
            "emulationBackend": "",
            "captureBackend": "",
            "emulationDummy": False,
            "captureStuck": False,
            "lastConnectError": "",
        }
    machines = []
    for peer in ts["peers"]:
        name = peer["name"]
        client = configured.get(name) or configured.get(peer["dnsName"]) or {}
        h = peer_health.get(name) or {}
        machines.append(
            {
                "name": name,
                "dnsName": peer["dnsName"],
                "os": peer["os"],
                "online": peer["online"],
                "shareable": peer["shareable"],
                "ips": peer["ips"],
                "configured": bool(client),
                "position": client.get("position") or "",
                "active": False,
                "authorized": name in authorized_by_name,
                "fingerprint": authorized_by_name.get(name, ""),
                "sshUser": ssh_users.get(name, ""),
                "remoteRunning": h.get("remoteRunning") if peer["online"] else None,
                "remoteUdp": bool(h.get("remoteUdp")),
                "remotePaired": h.get("remotePaired") if peer["online"] else None,
                "healthError": h.get("error") or "",
            }
        )
    last = {}
    try:
        from .remote import load_last

        last = load_last()
    except Exception:
        last = {}
    return {
        "ok": True,
        "pluginRoot": str(paths.PLUGIN_ROOT),
        "packageInstalled": version is not None,
        "packageVersion": version or "",
        "emulateReady": version is not None,
        "emulateError": "" if version else "lan-mouse is not installed",
        "daemonRunning": daemon_pid is not None,
        "daemonPid": daemon_pid or 0,
        "desiredOn": desired_on(),
        "clipboardEnabled": clipboard_on(),
        "fingerprint": fingerprint(),
        "port": int(cfg["port"]),
        "osUser": getpass.getuser(),
        "tailscale": {
            "installed": ts["installed"],
            "running": ts["running"],
            "selfName": ts["selfName"],
            "selfDns": ts["selfDns"],
            "selfIp": ts["selfIp"],
        },
        "machines": machines,
        "authorized": [{"fingerprint": fp, "name": name} for fp, name in cfg["authorized_fingerprints"].items()],
        "lastInstall": last,
        "emulationBackend": local.get("emulationBackend") or "",
        "captureBackend": local.get("captureBackend") or "",
        "emulationDummy": bool(local.get("emulationDummy")),
        "captureStuck": bool(local.get("captureStuck")),
        "lastConnectError": local.get("lastConnectError") or "",
    }


def _graphical_env() -> dict[str, str]:
    """Run lan-mouse in the compositor session so emulation is not dummy."""
    env = os.environ.copy()
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
    env.setdefault("XDG_RUNTIME_DIR", str(runtime))
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime}/bus")
    for sock in ("wayland-1", "wayland-0"):
        if (runtime / sock).exists() or (runtime / f"{sock}.lock").exists():
            env.setdefault("WAYLAND_DISPLAY", sock)
            break
    hypr_root = runtime / "hypr"
    if hypr_root.is_dir():
        for child in hypr_root.iterdir():
            if child.is_dir() and not child.name.endswith(".lock"):
                env.setdefault("HYPRLAND_INSTANCE_SIGNATURE", child.name)
                break
    for proc_dir in Path("/proc").iterdir():
        if not proc_dir.name.isdigit():
            continue
        try:
            cmd = (proc_dir / "comm").read_text().strip()
        except OSError:
            continue
        if cmd != "Hyprland":
            continue
        try:
            raw = (proc_dir / "environ").read_bytes()
        except OSError:
            break
        for item in raw.split(b"\0"):
            if b"=" not in item:
                continue
            key, val = item.split(b"=", 1)
            name = key.decode("utf-8", "replace")
            if name in (
                "WAYLAND_DISPLAY",
                "HYPRLAND_INSTANCE_SIGNATURE",
                "XDG_RUNTIME_DIR",
                "DBUS_SESSION_BUS_ADDRESS",
                "XDG_CURRENT_DESKTOP",
                "XDG_SESSION_TYPE",
                "XDG_BACKEND",
            ):
                env[name] = val.decode("utf-8", "replace")
        break
    env.setdefault("XDG_SESSION_TYPE", "wayland")
    env.setdefault("XDG_CURRENT_DESKTOP", "Hyprland")
    return env


def start_daemon() -> dict:
    paths.ensure()
    if package_version() is None:
        return {"ok": False, "error": "lan-mouse is not installed"}
    ts = tailscale.status()
    if not ts["running"]:
        return {"ok": False, "error": "Tailscale is not connected"}
    cfg = load_config()
    if pid_alive():
        set_desired("on")
        return build_status()
    write_config(cfg)
    with paths.LOG_PATH.open("wb") as log:
        proc = subprocess.Popen(
            ["lan-mouse", "--config", str(paths.CONFIG_PATH), "--cert-path", str(paths.CERT_PATH), "daemon"],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            cwd=str(Path.home()),
            env=_graphical_env(),
        )
    paths.PID_PATH.write_text(str(proc.pid) + "\n")
    set_desired("on")
    for _ in range(25):
        time.sleep(0.1)
        if proc.poll() is not None:
            paths.PID_PATH.unlink(missing_ok=True)
            return {"ok": False, "error": "lan-mouse exited during startup: " + paths.LOG_PATH.read_text(errors="replace")[-400:]}
        if fingerprint():
            break
    return build_status()


def release_pointer() -> dict:
    """Drop capture and start again so a stuck pointer returns here."""
    was_on = pid_alive() is not None or desired_on()
    if pid_alive():
        stop_daemon(forget_desired=False)
        time.sleep(0.2)
    if was_on:
        return start_daemon()
    return build_status()


def stop_daemon(*, forget_desired: bool = True) -> dict:
    if forget_desired:
        set_desired("off")
    pid = pid_alive()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        for _ in range(20):
            if not Path(f"/proc/{pid}").exists():
                break
            time.sleep(0.05)
        if Path(f"/proc/{pid}").exists():
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    try:
        paths.PID_PATH.unlink()
    except OSError:
        pass
    return build_status()


def add_peer(name: str, position: str) -> dict:
    if position not in ("left", "right", "top", "bottom"):
        return {"ok": False, "error": "position must be left, right, top or bottom"}
    peer = tailscale.find_peer(name)
    if peer is None:
        return {"ok": False, "error": f"no Tailscale machine named {name}"}
    if not peer["shareable"]:
        return {"ok": False, "error": f"{name} is {peer['os']}, which cannot run lan-mouse"}
    if not peer["ips"]:
        return {"ok": False, "error": f"{name} has no Tailscale IPv4 address"}
    name = peer["name"]
    cfg = load_config()
    existing = next((c for c in cfg["clients"] if c.get("hostname") in (name, peer["dnsName"])), {})
    others = [
        c
        for c in cfg["clients"]
        if c.get("hostname") not in (name, peer["dnsName"]) and c.get("position") != position
    ]
    hook = clipboard_hook(name, peer["ips"][0], peer["os"]) if clipboard_on() else ""
    others.append(
        {
            **existing,
            "hostname": name,
            "position": position,
            "port": existing.get("port", paths.PORT_DEFAULT),
            "ips": peer["ips"],
            "activate_on_startup": True,
            "enter_hook": hook,
        }
    )
    cfg["clients"] = others
    write_config(cfg)
    restart_if_running()
    return build_status()


def remove_peer(name: str) -> dict:
    cfg = load_config()
    cfg["clients"] = [c for c in cfg["clients"] if c.get("hostname") != name]
    write_config(cfg)
    restart_if_running()
    return build_status()


def authorize(name: str, fingerprint_value: str) -> dict:
    fp = fingerprint_value.strip().lower()
    if not config.valid_fingerprint(fp):
        return {"ok": False, "error": "that does not look like a lan-mouse fingerprint"}
    cfg = load_config()
    cfg["authorized_fingerprints"][fp] = name.strip() or "peer"
    write_config(cfg)
    restart_if_running()
    return build_status()


def deauthorize(fingerprint_value: str) -> dict:
    fp = fingerprint_value.strip().lower()
    cfg = load_config()
    cfg["authorized_fingerprints"].pop(fp, None)
    write_config(cfg)
    restart_if_running()
    return build_status()


def set_clipboard(enabled: bool) -> dict:
    cfg = load_config()
    peers = {p["name"]: p for p in tailscale.status()["peers"]}
    for client in cfg["clients"]:
        name = client.get("hostname") or ""
        peer = peers.get(name)
        ip = (peer["ips"][0] if peer and peer["ips"] else (client.get("ips") or [""])[0])
        os_name = peer["os"] if peer else "linux"
        client["enter_hook"] = clipboard_hook(name, ip, os_name) if enabled else ""
    write_config(cfg)
    set_clipboard_flag(enabled)
    restart_if_running()
    return build_status()


def probe_peers() -> dict:
    from .health import probe_configured

    cfg = load_config()
    probe_configured(cfg["clients"], fingerprint())
    return build_status()


def restart_peer(name: str, user: str = "", password: str = "") -> dict:
    from .health import restart_remote, probe_peer, load_peer_health, save_peer_health

    result = restart_remote(name, user=user, password=password)
    health = load_peer_health()
    peer_port = next((c.get("port", paths.PORT_DEFAULT) for c in load_config()["clients"] if c.get("hostname") == name), paths.PORT_DEFAULT)
    health[name] = probe_peer(name, fingerprint(), peer_port, user=user, password=password)
    save_peer_health(health)
    payload = build_status()
    if not result.get("ok"):
        payload["ok"] = False
        payload["error"] = result.get("error") or "could not restart lan-mouse there"
    return payload


def forget_peer(name: str) -> dict:
    from .health import restart_remote
    from .ssh import Session

    cfg = load_config()
    fps = [fp for fp, n in cfg["authorized_fingerprints"].items() if n == name]
    for fp in fps:
        cfg["authorized_fingerprints"].pop(fp, None)
    cfg["clients"] = [c for c in cfg["clients"] if c.get("hostname") != name]
    write_config(cfg)
    restart_if_running()
    peer = tailscale.find_peer(name)
    remote_error = ""
    if peer and peer.get("online"):
        from .remote import read_config, write_config_script, os_kind

        if os_kind(peer.get("os") or "") not in ("mac", "linux"):
            remote_error = "Remove this pairing manually on the other computer"
        else:
            sess = Session(name, peer)
            try:
                remote_cfg = read_config(sess)
                ts = tailscale.status()
                local_names = {n for n in (ts["selfName"], ts["selfDns"]) if n}
                local_fp = fingerprint()
                remote_cfg["authorized_fingerprints"] = {
                    fp: host for fp, host in remote_cfg["authorized_fingerprints"].items()
                    if fp != local_fp and host not in local_names
                }
                remote_cfg["clients"] = [
                    c for c in remote_cfg["clients"]
                    if c.get("hostname") not in local_names and not (ts["selfIp"] and ts["selfIp"] in c.get("ips", []))
                ]
                proc = sess.run_script("set -e\n" + write_config_script(remote_cfg), timeout=12)
                if proc.returncode:
                    remote_error = str(proc.stderr or "Could not remove remote pairing")
                else:
                    result = restart_remote(name)
                    remote_error = result.get("error") or ""
            except (ValueError, OSError) as exc:
                remote_error = str(exc)
    else:
        remote_error = "The peer is unavailable; remove this pairing there when it is online"
    from .health import load_peer_health, save_peer_health

    health = load_peer_health()
    health.pop(name, None)
    save_peer_health(health)
    payload = build_status()
    if remote_error:
        payload.update(ok=False, error="Forgot locally. " + remote_error)
    return payload


def copy_fingerprint() -> dict:
    fp = fingerprint()
    if not fp:
        return {"ok": False, "error": "no fingerprint yet; start the daemon once"}
    from .remote import copy_text

    result = copy_text(fp)
    result["fingerprint"] = fp
    return result


def install_packages() -> dict:
    proc = _run(["omarchy", "pkg", "add", "lan-mouse", "wl-clipboard"], timeout=180)
    if proc.returncode != 0:
        return {"ok": False, "error": (proc.stderr or proc.stdout or "install failed").strip()[:400]}
    return build_status()


def _read_password(use_stdin: bool) -> str:
    if not use_stdin:
        return ""
    return sys.stdin.readline().rstrip("\n\r")


def _activate_installed(name: str, user: str, password: str, result: dict) -> dict:
    from .remote import pair_peer, save_last

    if not result.get("installed"):
        return result
    if package_version() is None:
        result.update(paired=False, error="Install lan-mouse on this computer before pairing")
        save_last(result)
        return result
    if not pid_alive():
        started = start_daemon()
        if not started.get("ok"):
            result.update(paired=False, error=started.get("error") or "Could not start local lan-mouse")
            save_last(result)
            return result
    fp = fingerprint()

    if not fp:
        result["paired"] = False
        result["error"] = "No local fingerprint is available yet"
        result["log"] = ((result.get("log") or "") + "\nStart lan-mouse on this computer first so we have a fingerprint.").strip()
        save_last(result)
        return result
    ts = tailscale.status()
    cfg = load_config()
    pos = next((c.get("position") or "right" for c in cfg["clients"] if c.get("hostname") == name), "")
    if not pos:
        occupied = {c.get("position") for c in cfg["clients"]}
        pos = next((edge for edge in ("right", "left", "top", "bottom") if edge not in occupied), "")
        if not pos:
            result.update(paired=False, error="All local edges are occupied; select an edge first")
            save_last(result)
            return result
    peer = tailscale.find_peer(name)
    pair = pair_peer(
        name,
        peer,
        user=user,
        password=password,
        local_fp=fp,
        local_name=ts["selfName"],
        local_ip=ts["selfIp"],
        local_position=pos,
        local_port=cfg["port"],
    )
    log_bits = [result.get("log") or "", pair.get("log") or ""]
    result.update(pair)
    result["log"] = "\n".join(bit for bit in log_bits if bit).strip()
    result["installed"] = True
    if pair.get("paired") and pair.get("remoteFingerprint"):
        cfg = load_config()
        cfg["authorized_fingerprints"] = {fp: host for fp, host in cfg["authorized_fingerprints"].items() if host != name}
        cfg["authorized_fingerprints"][pair["remoteFingerprint"]] = name
        client = next((c for c in cfg["clients"] if c.get("hostname") == name), None)
        if client is None:
            occupied = {c.get("position") for c in cfg["clients"]}
            if pos in occupied:
                result.update(paired=False, error=f"The {pos} edge is already occupied; select an unused edge")
                save_last(result)
                return result
            client = {"hostname": name, "position": pos, "ips": peer["ips"], "activate_on_startup": True,
                      "enter_hook": clipboard_hook(name, peer["ips"][0], peer["os"]) if clipboard_on() else ""}
            cfg["clients"].append(client)
        client["port"] = pair["remotePort"]
        write_config(cfg)
        restart_if_running()
    save_last(result)
    return result


def install_peer(name: str, user: str = "", password: str = "") -> dict:
    from .remote import install_peer as do_install

    result = do_install(name, user=user, password=password)
    result = _activate_installed(name, user, password, result)
    payload = build_status()
    payload["lastInstall"] = result
    if result.get("error"):
        payload["ok"] = False
        payload["error"] = result["error"]
    elif not result.get("installed") and result.get("method") == "manual":
        payload["ok"] = True
    return payload


def retry_ssh(name: str, user: str = "", password: str = "") -> dict:
    from .remote import retry_ssh as do_retry

    result = do_retry(name, user=user, password=password)
    result = _activate_installed(name, user, password, result)
    payload = build_status()
    payload["lastInstall"] = result
    if result.get("error"):
        payload["ok"] = False
        payload["error"] = result["error"]
    return payload


def place_peer(name: str, position: str, user: str = "", password: str = "") -> dict:
    placed = add_peer(name, position)
    if placed.get("ok") is False:
        return placed
    peer = tailscale.find_peer(name)
    if peer and peer["os"].lower() == "windows":
        return placed
    return repair_peer(peer["name"] if peer else name, user, password)


def repair_peer(name: str, user: str = "", password: str = "") -> dict:
    result = {
        "name": name,
        "installed": True,
        "ok": True,
        "method": "repair",
        "log": "",
    }
    result = _activate_installed(name, user, password, result)
    payload = build_status()
    payload["lastInstall"] = result
    if result.get("error"):
        payload["ok"] = False
        payload["error"] = result["error"]
    return payload


def copy_instructions(name: str) -> dict:
    from .remote import copy_instructions as do_copy

    result = do_copy(name)
    payload = build_status()
    payload.update({k: result[k] for k in result if k != "ok"})
    if not result.get("ok"):
        payload["ok"] = False
        payload["error"] = result.get("error") or "copy failed"
    return payload


def restore() -> dict:
    if desired_on() and package_version() is not None:
        return start_daemon()
    return build_status()


def _main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="deskshare")
    parser.add_argument("verb")
    parser.add_argument("--name", default="")
    parser.add_argument("--position", default="right")
    parser.add_argument("--fingerprint", default="")
    parser.add_argument("--enabled", default="")
    parser.add_argument("--user", default="")
    parser.add_argument("--password-stdin", action="store_true")
    args = parser.parse_args(argv)
    verb = args.verb
    password = _read_password(args.password_stdin)
    if verb == "status":
        payload = build_status()
    elif verb == "start":
        payload = start_daemon()
    elif verb == "stop":
        payload = stop_daemon()
    elif verb == "release":
        payload = release_pointer()
    elif verb == "install":
        payload = install_packages()
    elif verb == "install-peer":
        payload = install_peer(args.name, user=args.user, password=password)
    elif verb == "retry-ssh":
        payload = retry_ssh(args.name, user=args.user, password=password)
    elif verb == "repair-peer":
        payload = repair_peer(args.name, user=args.user, password=password)
    elif verb == "place-peer":
        payload = place_peer(args.name, args.position, user=args.user, password=password)
    elif verb == "copy-instructions":
        payload = copy_instructions(args.name)
    elif verb == "restore":
        payload = restore()
    elif verb == "add-peer":
        payload = add_peer(args.name, args.position)
    elif verb == "remove-peer":
        payload = remove_peer(args.name)
    elif verb == "authorize":
        payload = authorize(args.name, args.fingerprint)
    elif verb == "deauthorize":
        payload = deauthorize(args.fingerprint)
    elif verb == "clipboard":
        if args.enabled not in ("on", "off"):
            payload = {"ok": False, "error": "clipboard --enabled on|off"}
        else:
            payload = set_clipboard(args.enabled == "on")
    elif verb == "copy-fingerprint":
        payload = copy_fingerprint()
    elif verb == "probe-peers":
        payload = probe_peers()
    elif verb == "restart-peer":
        payload = restart_peer(args.name, user=args.user, password=password)
    elif verb == "forget-peer":
        payload = forget_peer(args.name)
    else:
        payload = {"ok": False, "error": f"unknown verb {verb}"}
    print(json.dumps(payload, separators=(",", ":")))


def main(argv: list[str] | None = None) -> None:
    arguments = sys.argv[1:] if argv is None else argv
    try:
        paths.ensure()
        # Serialize read-modify-write actions across CLI and panel instances.
        with (paths.RUNTIME_DIR / "actions.lock").open("a") as lock:
            if arguments and arguments[0] not in ("status", "probe-peers"):
                fcntl.flock(lock, fcntl.LOCK_EX)
            _main(arguments)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))


if __name__ == "__main__":
    main()
