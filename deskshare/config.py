from __future__ import annotations

import json
from pathlib import Path

from .paths import CONFIG_PATH, PORT_DEFAULT, ensure


def load() -> dict:
    ensure()
    cfg = {
        "port": PORT_DEFAULT,
        "clipboard": True,
        "peers": [],
        "authorized": {},
        "seen": {},
    }
    if not CONFIG_PATH.exists():
        return cfg
    try:
        raw = json.loads(CONFIG_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return cfg
    if not isinstance(raw, dict):
        return cfg
    cfg["port"] = int(raw.get("port") or PORT_DEFAULT)
    cfg["clipboard"] = bool(raw.get("clipboard", True))
    peers = []
    for item in raw.get("peers") or []:
        if not isinstance(item, dict):
            continue
        peers.append(
            {
                "name": str(item.get("name") or ""),
                "ips": [str(ip) for ip in (item.get("ips") or [])],
                "position": str(item.get("position") or "right"),
                "port": int(item.get("port") or cfg["port"]),
            }
        )
    cfg["peers"] = [p for p in peers if p["name"]]
    auth = raw.get("authorized") or {}
    if isinstance(auth, dict):
        cfg["authorized"] = {str(k).lower(): str(v) for k, v in auth.items()}
    seen = raw.get("seen") or {}
    if isinstance(seen, dict):
        cfg["seen"] = {str(k).lower(): str(v) for k, v in seen.items()}
    return cfg


def save(cfg: dict) -> None:
    ensure()
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")
    CONFIG_PATH.chmod(0o600)


def desired_on() -> bool:
    from .paths import DESIRED_PATH

    try:
        return DESIRED_PATH.read_text().strip() == "on"
    except OSError:
        return False


def set_desired(value: str) -> None:
    from .paths import DESIRED_PATH

    ensure()
    DESIRED_PATH.write_text(value + "\n")
    DESIRED_PATH.chmod(0o600)
