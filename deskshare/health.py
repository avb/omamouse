"""Local log health and a cheap SSH probe of configured peers."""

from __future__ import annotations

import json
import time

from . import paths, tailscale
from .ssh import Session


def load_peer_health() -> dict:
    paths.ensure()
    if not paths.PEER_HEALTH_PATH.exists():
        return {}
    try:
        data = json.loads(paths.PEER_HEALTH_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_peer_health(data: dict) -> None:
    paths.ensure()
    paths.PEER_HEALTH_PATH.write_text(json.dumps(data, indent=2) + "\n")
    paths.PEER_HEALTH_PATH.chmod(0o600)


def local_health() -> dict:
    empty = {
        "emulationBackend": "",
        "captureBackend": "",
        "emulationDummy": False,
        "captureStuck": False,
        "lastConnectError": "",
    }
    if not paths.LOG_PATH.exists():
        return empty
    try:
        lines = paths.LOG_PATH.read_text(errors="replace").splitlines()[-400:]
    except OSError:
        return empty
    emu = ""
    cap = ""
    err = ""
    for line in reversed(lines):
        if "using emulation backend:" in line and not emu:
            emu = line.rsplit(":", 1)[-1].strip()
        if "using capture backend:" in line and not cap:
            cap = line.rsplit(":", 1)[-1].strip()
        if emu and cap:
            break
    tail_lines = lines[-25:]
    for line in reversed(tail_lines):
        if "failed to connect" in line or "did not respond" in line:
            err = line.split("] ", 1)[-1].strip()
            break
    tail = "\n".join(tail_lines)
    stuck = "releasing capture: not connected" in tail or (
        "entering client" in tail and "failed to connect" in tail
    )
    return {
        "emulationBackend": emu,
        "captureBackend": cap,
        "emulationDummy": emu == "dummy",
        "captureStuck": stuck,
        "lastConnectError": err[:200],
    }


def probe_peer(name: str, local_fp: str = "") -> dict:
    peer = tailscale.find_peer(name)
    result = {
        "name": name,
        "remoteRunning": False,
        "remoteUdp": False,
        "remotePaired": False,
        "remoteDummy": False,
        "ssh": False,
        "error": "",
        "checkedAt": int(time.time()),
    }
    if peer is None:
        result["error"] = "not on the tailnet"
        return result
    if not peer.get("online"):
        result["error"] = "offline"
        return result
    fp = (local_fp or "").lower()
    script = r"""
echo RUNNING=$(pgrep -x lan-mouse >/dev/null 2>&1 && echo yes || echo no)
if lsof -nP -iUDP:4242 >/dev/null 2>&1; then echo UDP=yes
elif netstat -an 2>/dev/null | grep -q '\.4242'; then echo UDP=yes
else echo UDP=no
fi
cfg="$HOME/.config/lan-mouse/config.toml"
if [ -f "$cfg" ]; then echo HAS_CONFIG=yes; else echo HAS_CONFIG=no; fi
echo CONFIG_HEAD
sed -n '1,80p' "$cfg" 2>/dev/null || true
echo CONFIG_TAIL
"""
    sess = Session(name, peer)
    proc = sess.run_script(script, timeout=10)
    out = (proc.stdout if isinstance(proc.stdout, str) else "") + "\n" + (
        proc.stderr if isinstance(proc.stderr, str) else ""
    )
    if proc.returncode not in (0, 1) and "RUNNING=" not in out:
        result["error"] = (proc.stderr if isinstance(proc.stderr, str) else "")[:160] or "ssh probe failed"
        result["ssh"] = False
        return result
    result["ssh"] = True
    result["remoteRunning"] = "RUNNING=yes" in out
    result["remoteUdp"] = "UDP=yes" in out
    if fp and fp in out.lower():
        result["remotePaired"] = True
    elif "HAS_CONFIG=yes" in out and fp:
        result["remotePaired"] = False
        result["error"] = "pairing missing on that machine"
    if not result["remoteRunning"] and result["ssh"]:
        result["error"] = result["error"] or "lan-mouse is not running there"
    elif result["remoteRunning"] and not result["remoteUdp"]:
        result["error"] = result["error"] or "not listening on UDP 4242"
    return result


def probe_configured(names: list[str], local_fp: str) -> dict:
    health = load_peer_health()
    for name in names:
        if not name:
            continue
        health[name] = probe_peer(name, local_fp)
    save_peer_health(health)
    return health


def restart_remote(name: str) -> dict:
    """Restart lan-mouse in the peer's graphical session and keep our pairing file."""
    from . import remote

    peer = tailscale.find_peer(name)
    if peer is None:
        return {"ok": False, "error": f"no Tailscale machine named {name}"}
    sess = Session(name, peer)
    kind = remote.os_kind(peer.get("os") or "")
    if kind == "mac":
        script = r"""
cfg="$HOME/.config/lan-mouse/config.toml"
tmp=$(mktemp)
if [ -f "$cfg" ]; then cp "$cfg" "$tmp"; fi
killall lan-mouse 2>/dev/null || true
sleep 0.4
open -a "Lan Mouse"
i=0
while [ "$i" -lt 20 ]; do
  pgrep -x lan-mouse >/dev/null 2>&1 && break
  i=$((i + 1))
  sleep 0.2
done
sleep 0.6
if [ -s "$tmp" ]; then
  mkdir -p "$HOME/.config/lan-mouse"
  cp "$tmp" "$cfg"
fi
rm -f "$tmp"
pgrep -x lan-mouse >/dev/null 2>&1 && echo restarted || echo not_running
"""
    else:
        script = r"""
pkill -x lan-mouse 2>/dev/null || true
sleep 0.3
if command -v lan-mouse >/dev/null; then
  nohup lan-mouse daemon >/tmp/lan-mouse.log 2>&1 &
fi
sleep 0.4
pgrep -x lan-mouse >/dev/null 2>&1 && echo restarted || echo not_running
"""
    proc = sess.run_script(script, timeout=20)
    out = (proc.stdout if isinstance(proc.stdout, str) else "") + (
        proc.stderr if isinstance(proc.stderr, str) else ""
    )
    ok = proc.returncode == 0 and "restarted" in out
    return {"ok": ok, "log": out.strip()[:400], "error": "" if ok else (out.strip()[:200] or "restart failed")}
