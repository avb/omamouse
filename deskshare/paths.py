from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

PLUGIN_ID = "io.github.avb.omamouse"
LEGACY_PLUGIN_IDS = (
    "io.github.dicebagstudios.omamouse",
    "io.github.dicebagstudios.omamice",
    "io.github.dicebagstudios.lan-mouse",
)
PORT_DEFAULT = 4242
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "lan-mouse"
CONFIG_PATH = CONFIG_DIR / "config.toml"
CERT_PATH = CONFIG_DIR / "lan-mouse.pem"
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / PLUGIN_ID
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}") / PLUGIN_ID
PID_PATH = RUNTIME_DIR / "lan-mouse.pid"
LOG_PATH = RUNTIME_DIR / "lan-mouse.log"
DESIRED_PATH = STATE_DIR / "desired"
CLIPBOARD_FLAG = STATE_DIR / "clipboard"
LAST_INSTALL_PATH = STATE_DIR / "last-install.json"
KNOWN_HOSTS_PATH = STATE_DIR / "ssh_known_hosts"
SSH_USERS_PATH = STATE_DIR / "ssh-users.json"
PEER_HEALTH_PATH = STATE_DIR / "peer-health.json"
PUSH_SCRIPT = PLUGIN_ROOT / "scripts" / "clipboard-push"
RELEASE_BIND = ["KeyLeftCtrl", "KeyLeftShift", "KeyLeftMeta", "KeyLeftAlt"]


def atomic_write(path: Path, text: str) -> None:
    """Readers see the old or new file, never a truncated intermediate file."""
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _adopt_legacy(dest: Path) -> None:
    if dest.exists():
        return
    for legacy_id in LEGACY_PLUGIN_IDS:
        src = dest.parent / legacy_id
        if src.exists() and src != dest:
            shutil.copytree(src, dest)
            return


def ensure() -> None:
    _adopt_legacy(STATE_DIR)
    _adopt_legacy(RUNTIME_DIR)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.chmod(0o700)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_DIR.chmod(0o700)
