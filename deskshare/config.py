"""Read and serialize configuration without discarding lan-mouse options."""

from __future__ import annotations

import datetime
import json
import re
import tomllib

from . import paths


def valid_fingerprint(value: str) -> bool:
    return re.fullmatch(r"[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){31}", value) is not None


def parse(text: str) -> dict:
    cfg = tomllib.loads(text)
    cfg.setdefault("port", paths.PORT_DEFAULT)
    cfg.setdefault("release_bind", list(paths.RELEASE_BIND))
    cfg.setdefault("authorized_fingerprints", {})
    cfg.setdefault("clients", [])
    port(cfg["port"])
    if not isinstance(cfg["release_bind"], list) or not all(isinstance(k, str) for k in cfg["release_bind"]):
        raise ValueError("release_bind must be a list of keys")
    fps = cfg["authorized_fingerprints"]
    if not isinstance(fps, dict) or not all(isinstance(v, str) for v in fps.values()):
        raise ValueError("authorized_fingerprints must be a table of names")
    cfg["authorized_fingerprints"] = {k.lower(): v for k, v in fps.items()}
    if not isinstance(cfg["clients"], list):
        raise ValueError("clients must be a list")
    for client in cfg["clients"]:
        if not isinstance(client, dict):
            raise ValueError("each client must be a table")
        port(client.get("port", paths.PORT_DEFAULT))
        for key in ("hostname", "position", "enter_hook"):
            if key in client and not isinstance(client[key], str):
                raise ValueError(f"client {key} must be a string")
        if "ips" in client and (not isinstance(client["ips"], list) or not all(isinstance(ip, str) for ip in client["ips"])):
            raise ValueError("client ips must be a list of addresses")
    return cfg


def port(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 65535:
        raise ValueError("port must be an integer between 1 and 65535")
    return value


def _value(value) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, list):
        return "[" + ", ".join(_value(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{_value(k)} = {_value(v)}" for k, v in value.items()) + " }"
    raise ValueError(f"unsupported TOML value: {type(value).__name__}")


def dumps(cfg: dict) -> str:
    text = "\n".join(f"{_value(k)} = {_value(v)}" for k, v in cfg.items()) + "\n"
    parse(text)  # Validate before replacing an existing configuration.
    return text
