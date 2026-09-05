from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
from pathlib import Path

from . import config, linux_emulate, paths, tailscale, tlsutil


def _pid_alive() -> int | None:
    try:
        pid = int(paths.PID_PATH.read_text().strip())
        os.kill(pid, 0)
    except (OSError, ValueError):
        return None
    return pid


def _talk(req: dict) -> dict | None:
    if _pid_alive() is None:
        return None
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(4)
        sock.connect(str(paths.SOCK_PATH))
        sock.sendall((json.dumps(req) + "\n").encode())
        data = b""
        while b"\n" not in data:
            piece = sock.recv(65536)
            if not piece:
                break
            data += piece
        sock.close()
        return json.loads(data.decode())
    except Exception:
        return None


def build_status() -> dict:
    ts = tailscale.status()
    cfg = config.load()
    emu_ok, emu_err = (False, "not linux")
    if sys.platform.startswith("linux"):
        emu_ok, emu_err = linux_emulate.ready()
    fp = ""
    try:
        fp = tlsutil.fingerprint()
    except Exception:
        pass
    configured = {p["name"]: p for p in cfg.get("peers") or []}
    authorized_by_name = {name: f for f, name in (cfg.get("authorized") or {}).items()}
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
    return {
        "ok": True,
        "pluginRoot": str(paths.PLUGIN_ROOT),
        "packageInstalled": emu_ok or not sys.platform.startswith("linux"),
        "packageVersion": "deskshare",
        "emulateReady": emu_ok,
        "emulateError": emu_err,
        "daemonRunning": _pid_alive() is not None,
        "daemonPid": _pid_alive() or 0,
        "desiredOn": config.desired_on(),
        "clipboardEnabled": bool(cfg.get("clipboard", True)),
        "fingerprint": fp,
        "port": int(cfg.get("port") or paths.PORT_DEFAULT),
        "tailscale": {
            "installed": ts["installed"],
            "running": ts["running"],
            "selfName": ts["selfName"],
            "selfDns": ts["selfDns"],
            "selfIp": ts["selfIp"],
        },
        "machines": machines,
        "authorized": [{"fingerprint": f, "name": n} for f, n in (cfg.get("authorized") or {}).items()],
        "seen": [{"fingerprint": f, "name": n} for f, n in (cfg.get("seen") or {}).items()],
    }


def handle(verb: str, args: dict, daemon=None) -> dict:
    if verb == "status":
        return build_status()
    if verb == "add-peer":
        name = str(args.get("name") or "")
        position = str(args.get("position") or "right")
        if position not in ("left", "right", "top", "bottom"):
            return {"ok": False, "error": "position must be left, right, top or bottom"}
        peer = tailscale.find_peer(name)
        if peer is None:
            return {"ok": False, "error": f"no Tailscale machine named {name}"}
        if not peer["shareable"]:
            return {"ok": False, "error": f"{name} cannot run Deskshare"}
        if not peer["ips"]:
            return {"ok": False, "error": f"{name} has no Tailscale IPv4"}
        cfg = config.load()
        cfg["peers"] = [p for p in cfg["peers"] if p["name"] != name]
        cfg["peers"].append({"name": name, "ips": peer["ips"], "position": position, "port": cfg["port"]})
        config.save(cfg)
        if daemon:
            daemon.reload()
        return build_status()
    if verb == "remove-peer":
        name = str(args.get("name") or "")
        cfg = config.load()
        cfg["peers"] = [p for p in cfg["peers"] if p["name"] != name]
        config.save(cfg)
        if daemon:
            daemon.reload()
        return build_status()
    if verb == "authorize":
        name = str(args.get("name") or "peer").strip()
        fp = str(args.get("fingerprint") or "").strip().lower()
        if ":" not in fp:
            return {"ok": False, "error": "that does not look like a fingerprint"}
        cfg = config.load()
        cfg.setdefault("authorized", {})[fp] = name
        config.save(cfg)
        if daemon:
            daemon.reload()
        return build_status()
    if verb == "deauthorize":
        fp = str(args.get("fingerprint") or "").strip().lower()
        cfg = config.load()
        cfg.get("authorized", {}).pop(fp, None)
        config.save(cfg)
        if daemon:
            daemon.reload()
        return build_status()
    if verb == "clipboard":
        enabled = str(args.get("enabled") or "") == "on"
        cfg = config.load()
        cfg["clipboard"] = enabled
        config.save(cfg)
        if daemon:
            daemon.cfg = cfg
        return build_status()
    if verb == "copy-fingerprint":
        fp = tlsutil.fingerprint()
        if shutil.which("wl-copy"):
            subprocess.run(["wl-copy"], input=(fp + "\n").encode(), check=False, timeout=2)
        return {"ok": True, "fingerprint": fp, "copied": True}
    return {"ok": False, "error": f"unknown verb {verb}"}


def start_daemon() -> dict:
    paths.ensure()
    ts = tailscale.status()
    if not ts["running"]:
        return {"ok": False, "error": "Tailscale is not connected"}
    if _pid_alive():
        config.set_desired("on")
        return build_status()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(paths.PLUGIN_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    log = paths.LOG_PATH.open("ab")
    proc = subprocess.Popen(
        [sys.executable, "-m", "deskshare", "daemon"],
        cwd=str(paths.PLUGIN_ROOT),
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    paths.PID_PATH.write_text(str(proc.pid) + "\n")
    config.set_desired("on")
    return build_status()


def stop_daemon() -> dict:
    config.set_desired("off")
    pid = _pid_alive()
    if pid:
        os.kill(pid, signal.SIGTERM)
    try:
        paths.PID_PATH.unlink()
    except OSError:
        pass
    try:
        paths.SOCK_PATH.unlink()
    except OSError:
        pass
    return build_status()


def install_packages() -> dict:
    setup = paths.PLUGIN_ROOT / "setup"
    proc = subprocess.run([str(setup)], check=False, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        return {"ok": False, "error": (proc.stderr or proc.stdout or "setup failed").strip()[:400]}
    return build_status()


def restore() -> dict:
    if config.desired_on():
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
    payload: dict
    if verb == "start":
        payload = start_daemon()
    elif verb == "stop":
        payload = stop_daemon()
    elif verb == "install":
        payload = install_packages()
    elif verb == "restore":
        payload = restore()
    elif verb in ("status", "add-peer", "remove-peer", "authorize", "deauthorize", "clipboard", "copy-fingerprint"):
        req = {
            "verb": verb,
            "name": args.name,
            "position": args.position,
            "fingerprint": args.fingerprint,
            "enabled": args.enabled,
        }
        live = _talk(req) if verb != "status" else None
        payload = live if live is not None else handle(verb, req)
        if verb == "status":
            payload = build_status()
    else:
        payload = {"ok": False, "error": f"unknown verb {verb}"}
    print(json.dumps(payload, separators=(",", ":")))
