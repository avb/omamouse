from __future__ import annotations

import os
from pathlib import Path

PLUGIN_ID = "io.github.dicebagstudios.lan-mouse"
PORT_DEFAULT = 4242
TAILSCALE_CGNAT = "100.64.0.0/10"

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path.home() / ".config" / "deskshare"
CONFIG_PATH = CONFIG_DIR / "config.json"
CERT_PATH = CONFIG_DIR / "cert.pem"
KEY_PATH = CONFIG_DIR / "key.pem"
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / PLUGIN_ID
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / PLUGIN_ID
PID_PATH = RUNTIME_DIR / "deskshare.pid"
LOG_PATH = RUNTIME_DIR / "deskshare.log"
SOCK_PATH = RUNTIME_DIR / "control.sock"
DESIRED_PATH = STATE_DIR / "desired"


def ensure() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.chmod(0o700)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.chmod(0o700)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_DIR.chmod(0o700)
