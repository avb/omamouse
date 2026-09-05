from __future__ import annotations

import ipaddress
import queue
import socket
import threading
import time
from typing import Callable

from . import protocol, tlsutil
from .paths import TAILSCALE_CGNAT

CGNAT = ipaddress.ip_network(TAILSCALE_CGNAT)


def allowed_ip(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip) in CGNAT
    except ValueError:
        return False


class Mesh:
    """TLS server plus one outbound connection per peer, Tailscale IPv4 only."""

    def __init__(self, bind_ip: str, port: int, authorized: dict[str, str], on_msg: Callable[[str, dict], None], on_seen: Callable[[str, str], None]):
        self.bind_ip = bind_ip
        self.port = port
        self.authorized = dict(authorized)
        self.on_msg = on_msg
        self.on_seen = on_seen
        self.peers: dict[str, dict] = {}
        self._socks: dict[str, socket.socket] = {}
        self._queues: dict[str, queue.Queue] = {}
        self._started: set[str] = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._serve, name="deskshare-listen", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            for sock in list(self._socks.values()):
                try:
                    sock.close()
                except OSError:
                    pass

    def set_authorized(self, authorized: dict[str, str]) -> None:
        self.authorized = dict(authorized)

    def ensure_peer(self, name: str, ip: str, port: int) -> None:
        start = False
        with self._lock:
            self.peers[name] = {"ip": ip, "port": port}
            if name not in self._queues:
                self._queues[name] = queue.Queue(maxsize=256)
            if name not in self._started:
                self._started.add(name)
                start = True
        if start:
            threading.Thread(target=self._client_loop, args=(name,), name=f"deskshare-out-{name}", daemon=True).start()

    def send(self, name: str, msg: dict) -> None:
        q = self._queues.get(name)
        if q is None:
            return
        try:
            q.put_nowait(msg)
        except queue.Full:
            try:
                q.get_nowait()
            except queue.Empty:
                pass
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass

    def _serve(self) -> None:
        if not allowed_ip(self.bind_ip):
            return
        ctx = tlsutil.server_context()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.bind_ip, self.port))
        sock.listen(8)
        sock.settimeout(1)
        while not self._stop.is_set():
            try:
                conn, addr = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if not allowed_ip(addr[0]):
                conn.close()
                continue
            threading.Thread(target=self._inbound, args=(conn,), name="deskshare-in", daemon=True).start()

    def _inbound(self, conn: socket.socket) -> None:
        ctx = tlsutil.server_context()
        try:
            ssock = ctx.wrap_socket(conn, server_side=True)
            fp = tlsutil.peer_fingerprint(ssock)
            name = self.authorized.get(fp, "")
            self.on_seen(fp, name or "unknown")
            if fp not in self.authorized:
                ssock.sendall(protocol.encode({"t": "reject", "reason": "unauthorized"}))
                ssock.close()
                return
            ssock.settimeout(30)
            while not self._stop.is_set():
                msg = protocol.read_frame(ssock)
                if msg is None:
                    break
                self.on_msg(name, msg)
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _client_loop(self, name: str) -> None:
        ctx = tlsutil.client_context()
        while not self._stop.is_set():
            peer = self.peers.get(name)
            if not peer:
                time.sleep(1)
                continue
            if not allowed_ip(peer["ip"]):
                time.sleep(2)
                continue
            try:
                raw = socket.create_connection((peer["ip"], peer["port"]), timeout=4)
                ssock = ctx.wrap_socket(raw, server_hostname=name)
                fp = tlsutil.peer_fingerprint(ssock)
                self.on_seen(fp, name)
                if fp and fp not in self.authorized:
                    ssock.close()
                    time.sleep(3)
                    continue
                with self._lock:
                    self._socks[name] = ssock
                ssock.settimeout(0.2)
                q = self._queues[name]
                while not self._stop.is_set():
                    try:
                        msg = q.get(timeout=0.2)
                        ssock.sendall(protocol.encode(msg))
                    except queue.Empty:
                        pass
                    except OSError:
                        break
            except Exception:
                time.sleep(2)
            finally:
                with self._lock:
                    self._socks.pop(name, None)
