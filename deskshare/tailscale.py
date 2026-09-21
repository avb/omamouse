from __future__ import annotations

import json
import shutil
import subprocess


def _run(cmd: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return subprocess.CompletedProcess(cmd, 127, "", "")


def status() -> dict:
    empty = {
        "installed": shutil.which("tailscale") is not None,
        "running": False,
        "selfName": "",
        "selfDns": "",
        "selfIp": "",
        "peers": [],
    }
    if not empty["installed"]:
        return empty
    proc = _run(["tailscale", "status", "--json"])
    if proc.returncode != 0:
        return empty
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return empty
    if not isinstance(data, dict):
        return empty
    self_info = data.get("Self") or {}
    if not isinstance(self_info, dict):
        return empty
    ips = [ip for ip in (self_info.get("TailscaleIPs") or []) if ":" not in ip]
    dns = str(self_info.get("DNSName") or "").rstrip(".")
    host = dns.split(".")[0] if dns else str(self_info.get("HostName") or "")
    peers = []
    peer_data = data.get("Peer") or {}
    if not isinstance(peer_data, dict):
        return empty
    for node in peer_data.values():
        if not isinstance(node, dict):
            continue
        os_name = str(node.get("OS") or "")
        peer_ips = [ip for ip in (node.get("TailscaleIPs") or []) if ":" not in ip]
        peer_dns = str(node.get("DNSName") or "").rstrip(".")
        name = peer_dns.split(".")[0] if peer_dns else str(node.get("HostName") or "")
        shareable = os_name.lower() in ("linux", "windows", "macos", "mac os", "darwin")
        peers.append(
            {
                "name": name,
                "dnsName": peer_dns,
                "os": os_name,
                "online": bool(node.get("Online")),
                "ips": peer_ips,
                "shareable": shareable,
            }
        )
    peers.sort(key=lambda p: (not p["online"], p["name"].lower()))
    return {
        "installed": True,
        "running": str(data.get("BackendState") or "") == "Running" and bool(ips),
        "selfName": host,
        "selfDns": dns,
        "selfIp": ips[0] if ips else "",
        "peers": peers,
    }


def find_peer(name: str) -> dict | None:
    for peer in status()["peers"]:
        if peer["name"] == name or peer["dnsName"] == name:
            return peer
    return None
