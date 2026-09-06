from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import paths, tailscale

try:
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None  # type: ignore


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
        os.kill(pid, 0)
    except (OSError, ValueError):
        return None
    cmdline = Path(f"/proc/{pid}/cmdline")
    try:
        args = cmdline.read_bytes().replace(b"\x00", b" ").decode()
    except OSError:
        args = ""
    if "lan-mouse" not in args:
        return None
    return pid


def desired_on() -> bool:
    try:
        return paths.DESIRED_PATH.read_text().strip() == "on"
    except OSError:
        return False


def set_desired(value: str) -> None:
    paths.ensure()
    paths.DESIRED_PATH.write_text(value + "\n")
    paths.DESIRED_PATH.chmod(0o600)


def clipboard_on() -> bool:
    try:
        return paths.CLIPBOARD_FLAG.read_text().strip() != "off"
    except OSError:
        return True


def set_clipboard_flag(enabled: bool) -> None:
    paths.ensure()
    paths.CLIPBOARD_FLAG.write_text(("on" if enabled else "off") + "\n")
    paths.CLIPBOARD_FLAG.chmod(0o600)


def load_config() -> dict:
    cfg = {
        "port": paths.PORT_DEFAULT,
        "release_bind": list(paths.RELEASE_BIND),
        "authorized_fingerprints": {},
        "clients": [],
    }
    if not paths.CONFIG_PATH.exists() or tomllib is None:
        return cfg
    try:
        raw = tomllib.loads(paths.CONFIG_PATH.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return cfg
    cfg["port"] = int(raw.get("port") or paths.PORT_DEFAULT)
    if isinstance(raw.get("release_bind"), list) and raw["release_bind"]:
        cfg["release_bind"] = [str(x) for x in raw["release_bind"]]
    fps = raw.get("authorized_fingerprints") or {}
    if isinstance(fps, dict):
        cfg["authorized_fingerprints"] = {str(k).lower(): str(v) for k, v in fps.items()}
    clients = []
    for item in raw.get("clients") or []:
        if not isinstance(item, dict):
            continue
        clients.append(
            {
                "hostname": str(item.get("hostname") or ""),
                "position": str(item.get("position") or "right"),
                "port": int(item.get("port") or cfg["port"]),
                "ips": [str(ip) for ip in (item.get("ips") or [])],
                "activate_on_startup": True,
                "enter_hook": str(item.get("enter_hook") or ""),
            }
        )
    cfg["clients"] = clients
    return cfg


def _esc(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def clipboard_hook(name: str, ip: str, os_name: str) -> str:
    return f"{paths.PUSH_SCRIPT} {name} {ip} {os_name.replace(' ', '')}"


def write_config(cfg: dict) -> None:
    paths.ensure()
    lines = [
        f"port = {int(cfg.get('port') or paths.PORT_DEFAULT)}",
        "release_bind = [" + ", ".join(f'"{_esc(k)}"' for k in (cfg.get("release_bind") or paths.RELEASE_BIND)) + "]",
        "",
        "[authorized_fingerprints]",
    ]
    fps = cfg.get("authorized_fingerprints") or {}
    if not fps:
        lines.append("# paste a peer fingerprint so it can control this machine")
    for fp, name in fps.items():
        lines.append(f'"{_esc(fp)}" = "{_esc(name)}"')
    lines.append("")
    for client in cfg.get("clients") or []:
        lines.append("[[clients]]")
        lines.append(f'position = "{_esc(client.get("position") or "right")}"')
        host = client.get("hostname") or ""
        if host:
            lines.append(f'hostname = "{_esc(host)}"')
        ips = client.get("ips") or []
        if ips:
            lines.append("ips = [" + ", ".join(f'"{_esc(ip)}"' for ip in ips) + "]")
        lines.append(f"port = {int(client.get('port') or cfg.get('port') or paths.PORT_DEFAULT)}")
        lines.append("activate_on_startup = true")
        hook = client.get("enter_hook") or ""
        if hook:
            lines.append(f'enter_hook = "{_esc(hook)}"')
        lines.append("")
    paths.CONFIG_PATH.write_text("\n".join(lines).rstrip() + "\n")
    paths.CONFIG_PATH.chmod(0o600)


def restart_if_running() -> None:
    if pid_alive():
        stop_daemon(forget_desired=False)
        time.sleep(0.2)
        start_daemon()


def build_status() -> dict:
    ts = tailscale.status()
    cfg = load_config()
    version = package_version()
    daemon_pid = pid_alive()
    authorized_by_name = {name: fp for fp, name in cfg["authorized_fingerprints"].items()}
    configured = {c["hostname"]: c for c in cfg["clients"] if c.get("hostname")}
    machines = []
    for peer in ts["peers"]:
        name = peer["name"]
        client = configured.get(name) or {}
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
    }


def start_daemon() -> dict:
    paths.ensure()
    if package_version() is None:
        return {"ok": False, "error": "lan-mouse is not installed"}
    ts = tailscale.status()
    if not ts["running"]:
        return {"ok": False, "error": "Tailscale is not connected"}
    write_config(load_config())
    if pid_alive():
        set_desired("on")
        return build_status()
    log = paths.LOG_PATH.open("ab")
    proc = subprocess.Popen(
        ["lan-mouse", "daemon"],
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        cwd=str(Path.home()),
    )
    paths.PID_PATH.write_text(str(proc.pid) + "\n")
    set_desired("on")
    for _ in range(25):
        if fingerprint():
            break
        time.sleep(0.1)
    return build_status()


def stop_daemon(*, forget_desired: bool = True) -> dict:
    if forget_desired:
        set_desired("off")
    pid = pid_alive()
    if pid:
        os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            if not Path(f"/proc/{pid}").exists():
                break
            time.sleep(0.05)
        if Path(f"/proc/{pid}").exists():
            os.kill(pid, signal.SIGKILL)
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
    cfg = load_config()
    others = [c for c in cfg["clients"] if c.get("hostname") != name]
    hook = clipboard_hook(name, peer["ips"][0], peer["os"]) if clipboard_on() else ""
    others.append(
        {
            "hostname": name,
            "position": position,
            "port": cfg["port"],
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
    if ":" not in fp or len(fp) < 32:
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
    set_clipboard_flag(enabled)
    cfg = load_config()
    peers = {p["name"]: p for p in tailscale.status()["peers"]}
    for client in cfg["clients"]:
        name = client.get("hostname") or ""
        peer = peers.get(name)
        ip = (peer["ips"][0] if peer and peer["ips"] else (client.get("ips") or [""])[0])
        os_name = peer["os"] if peer else "linux"
        client["enter_hook"] = clipboard_hook(name, ip, os_name) if enabled else ""
    write_config(cfg)
    restart_if_running()
    return build_status()


def copy_fingerprint() -> dict:
    fp = fingerprint()
    if not fp:
        return {"ok": False, "error": "no fingerprint yet; start the daemon once"}
    if shutil.which("wl-copy"):
        subprocess.run(["wl-copy"], input=(fp + "\n").encode(), check=False, timeout=2)
    return {"ok": True, "fingerprint": fp, "copied": True}


def install_packages() -> dict:
    proc = _run(["omarchy", "pkg", "add", "lan-mouse", "wl-clipboard"], timeout=180)
    if proc.returncode != 0:
        return {"ok": False, "error": (proc.stderr or proc.stdout or "install failed").strip()[:400]}
    return build_status()


def install_peer(name: str) -> dict:
    from .remote import install_peer as do_install

    result = do_install(name)
    payload = build_status()
    payload["lastInstall"] = result
    if result.get("error"):
        payload["ok"] = False
        payload["error"] = result["error"]
    elif not result.get("installed") and result.get("method") == "manual":
        payload["ok"] = True
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


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="deskshare")
    parser.add_argument("verb")
    parser.add_argument("--name", default="")
    parser.add_argument("--position", default="right")
    parser.add_argument("--fingerprint", default="")
    parser.add_argument("--enabled", default="")
    args = parser.parse_args(argv)
    verb = args.verb
    if verb == "status":
        payload = build_status()
    elif verb == "start":
        payload = start_daemon()
    elif verb == "stop":
        payload = stop_daemon()
    elif verb == "install":
        payload = install_packages()
    elif verb == "install-peer":
        payload = install_peer(args.name)
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
    else:
        payload = {"ok": False, "error": f"unknown verb {verb}"}
    print(json.dumps(payload, separators=(",", ":")))


if __name__ == "__main__":
    main()
