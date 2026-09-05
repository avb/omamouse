from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import threading
from . import config, linux_emulate, paths, tailscale, tlsutil
from .net import Mesh


def _paste() -> str:
    try:
        proc = subprocess.run(["wl-paste", "-n"], capture_output=True, timeout=1)
        return proc.stdout.decode("utf-8", "replace")
    except Exception:
        return ""


class Daemon:
    def __init__(self) -> None:
        self.cfg = config.load()
        self.ts = tailscale.status()
        self.mesh: Mesh | None = None
        self.capture = None
        self._stop = threading.Event()

    def run(self) -> None:
        paths.ensure()
        tlsutil.ensure_cert()
        if not self.ts["running"] or not self.ts["selfIp"]:
            print("deskshare: Tailscale is not connected", file=sys.stderr)
            raise SystemExit(1)
        paths.PID_PATH.write_text(str(os.getpid()) + "\n")
        paths.PID_PATH.chmod(0o600)
        config.set_desired("on")
        self.mesh = Mesh(
            bind_ip=self.ts["selfIp"],
            port=int(self.cfg["port"]),
            authorized=self.cfg["authorized"],
            on_msg=self._on_msg,
            on_seen=self._on_seen,
        )
        self.mesh.start()
        self._connect_peers()
        if sys.platform.startswith("linux"):
            from .linux_capture import Capture

            self.capture = Capture(self._on_capture, self._edges())
            try:
                self.capture.start()
            except Exception as exc:
                print(f"deskshare: capture not started: {exc}", file=sys.stderr)
        self._serve_ctl()

    def _edges(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for peer in self.cfg.get("peers") or []:
            pos = peer.get("position") or "right"
            out[pos] = peer["name"]
        return out

    def _connect_peers(self) -> None:
        assert self.mesh is not None
        for peer in self.cfg.get("peers") or []:
            ips = peer.get("ips") or []
            if not ips:
                continue
            self.mesh.ensure_peer(peer["name"], ips[0], int(peer.get("port") or self.cfg["port"]))

    def _on_capture(self, msg: dict) -> None:
        if self.mesh is None:
            return
        peer = msg.get("peer")
        if not peer:
            return
        if msg.get("t") == "enter" and self.cfg.get("clipboard"):
            text = _paste()
            if text:
                self.mesh.send(peer, {"t": "clip", "text": text[:8000]})
        wire = dict(msg)
        wire.pop("peer", None)
        self.mesh.send(peer, wire)

    def _on_msg(self, name: str, msg: dict) -> None:
        kind = msg.get("t")
        if kind in ("move", "button", "wheel", "key", "clip"):
            if sys.platform == "darwin":
                from . import macos_input

                macos_input.handle(msg)
            else:
                try:
                    linux_emulate.handle(msg)
                except Exception:
                    pass

    def _on_seen(self, fingerprint: str, name: str) -> None:
        if not fingerprint:
            return
        self.cfg.setdefault("seen", {})[fingerprint] = name
        config.save(self.cfg)

    def reload(self) -> None:
        self.cfg = config.load()
        if self.mesh:
            self.mesh.set_authorized(self.cfg.get("authorized") or {})
            self._connect_peers()
        if self.capture is not None:
            self.capture.set_edges(self._edges())
            try:
                from gi.repository import GLib

                GLib.idle_add(self.capture._build_sensors)
            except Exception:
                pass

    def _serve_ctl(self) -> None:
        sock_path = paths.SOCK_PATH
        try:
            sock_path.unlink()
        except OSError:
            pass
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(str(sock_path))
        sock.listen(4)
        sock_path.chmod(0o600)
        while not self._stop.is_set():
            try:
                conn, _ = sock.accept()
            except OSError:
                break
            threading.Thread(target=self._ctl_one, args=(conn,), daemon=True).start()

    def _ctl_one(self, conn: socket.socket) -> None:
        with conn:
            data = b""
            while b"\n" not in data:
                piece = conn.recv(4096)
                if not piece:
                    return
                data += piece
            try:
                req = json.loads(data.decode())
            except json.JSONDecodeError:
                conn.sendall(b'{"ok":false,"error":"bad json"}\n')
                return
            try:
                from .ctl import handle as handle_ctl

                payload = handle_ctl(req.get("verb"), req, daemon=self)
            except Exception as exc:
                payload = {"ok": False, "error": str(exc)}
            conn.sendall((json.dumps(payload) + "\n").encode())


def run_daemon() -> None:
    paths.ensure()
    log = paths.LOG_PATH.open("ab", buffering=1)
    os.dup2(log.fileno(), 1)
    os.dup2(log.fileno(), 2)
    daemon = Daemon()

    def _stop(*_a) -> None:
        config.set_desired("off")
        if daemon.mesh:
            daemon.mesh.stop()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _stop)
    daemon.run()
