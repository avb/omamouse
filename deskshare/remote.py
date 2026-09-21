from __future__ import annotations

import json
import shlex
import subprocess

from . import paths, tailscale
from .ssh import Session, install_login_key, save_user

MAC_ARM = "https://github.com/feschber/lan-mouse/releases/latest/download/lan-mouse-macos-arm64.zip"
MAC_INTEL = "https://github.com/feschber/lan-mouse/releases/latest/download/lan-mouse-macos-intel.zip"
WIN_ZIP = "https://github.com/feschber/lan-mouse/releases/latest/download/lan-mouse-windows-x86_64.zip"
LINUX_X64 = "https://github.com/feschber/lan-mouse/releases/latest/download/lan-mouse-linux-x86_64"


def os_kind(os_name: str) -> str:
    n = (os_name or "").lower()
    if "mac" in n or n == "darwin":
        return "mac"
    if "win" in n:
        return "windows"
    if "linux" in n:
        return "linux"
    return "other"


def instructions(name: str, os_name: str) -> str:
    kind = os_kind(os_name)
    if kind == "mac":
        return (
            f"Install lan-mouse on {name} (macOS)\n"
            "\n"
            "1. Download the zip for this Mac:\n"
            f"   Apple Silicon: {MAC_ARM}\n"
            f"   Intel: {MAC_INTEL}\n"
            "2. Unzip it.\n"
            "3. In Terminal: xattr -rd com.apple.quarantine \"Lan Mouse.app\"\n"
            "4. Drag Lan Mouse.app into Applications and open it.\n"
            "5. Grant Accessibility when macOS asks.\n"
            "6. Copy the fingerprint from Lan Mouse and paste it here under Allow a peer in.\n"
            "\n"
            "If usernames differ or there is no key, enter the SSH user and password in the panel\n"
            "and click Retry SSH. The password is not stored. If it works we copy this computer's\n"
            "public key over so the next login does not need it."
        )
    if kind == "windows":
        return (
            f"Install lan-mouse on {name} (Windows)\n"
            "\n"
            f"1. Download {WIN_ZIP}\n"
            "2. Unzip it and run lan-mouse.exe.\n"
            "3. Allow it through Windows Firewall if asked (UDP 4242).\n"
            "4. Copy the fingerprint from the window and paste it here under Allow a peer in.\n"
            "\n"
            "Windows cannot be installed from this panel. Tailscale SSH is not used here."
        )
    if kind == "linux":
        return (
            f"Install lan-mouse on {name} (Linux)\n"
            "\n"
            "Arch / Omarchy: sudo pacman -S lan-mouse\n"
            "Fedora (Terra): sudo dnf install lan-mouse\n"
            f"Or download {LINUX_X64}, chmod +x, and put it on PATH.\n"
            "Then start `lan-mouse`, copy the fingerprint, and paste it here."
        )
    return f"No automatic installer for {name} ({os_name or 'unknown OS'})."


def load_last() -> dict:
    paths.ensure()
    if not paths.LAST_INSTALL_PATH.exists():
        return {}
    try:
        data = json.loads(paths.LAST_INSTALL_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_last(data: dict) -> None:
    paths.ensure()
    paths.LAST_INSTALL_PATH.write_text(json.dumps(data, indent=2) + "\n")
    paths.LAST_INSTALL_PATH.chmod(0o600)


def _clip(text: str, limit: int = 800) -> str:
    text = (text or "").strip()
    if len(text) > limit:
        return text[:limit] + "…"
    return text


def _whoami(stdout: str) -> str:
    lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
    if len(lines) >= 2 and lines[0] == "ok":
        return lines[1]
    return ""


def _after_ssh(sess: Session, name: str, password: str, ssh_ok: bool, result: dict, stdout: str = "") -> dict:
    result["sshUser"] = sess.user
    result["needAuth"] = not ssh_ok
    result["keyCopied"] = False
    if not ssh_ok:
        return result
    who = sess.user or _whoami(stdout)
    if who:
        save_user(name, who)
        result["sshUser"] = who
    if password:
        result["keyCopied"] = install_login_key(sess)
    return result


def install_mac(name: str, peer: dict | None = None, user: str = "", password: str = "") -> dict:
    sess = Session(name, peer, user=user, password=password)
    probe = sess.run_script(
        "eval \"$(/opt/homebrew/bin/brew shellenv 2>/dev/null)\"; eval \"$(/usr/local/bin/brew shellenv 2>/dev/null)\"; command -v brew; uname -m; echo ---; test -d '/Applications/Lan Mouse.app' && echo app_present || true",
        timeout=15,
    )
    ssh_ok = probe.returncode == 0
    stdout = probe.stdout if isinstance(probe.stdout, str) else ""
    stderr = probe.stderr if isinstance(probe.stderr, str) else ""
    out = stdout + stderr
    has_brew = ssh_ok and any(line.rstrip().endswith("brew") for line in stdout.splitlines())
    arch = "arm64"
    for line in stdout.splitlines():
        if line.strip() in ("arm64", "x86_64"):
            arch = line.strip()
    result = {
        "name": name,
        "os": "macOS",
        "ssh": ssh_ok,
        "sshVia": sess.via,
        "sshTarget": sess.target,
        "brew": has_brew,
        "method": "manual",
        "installed": False,
        "log": _clip(out),
        "instructions": instructions(name, "macOS"),
        "needAuth": False,
        "sshUser": sess.user,
        "keyCopied": False,
    }
    result = _after_ssh(sess, name, password, ssh_ok, result, stdout)
    if not ssh_ok:
        result["log"] = _clip(
            out
            or "SSH did not connect. Enter the SSH user and password for that machine, then Retry SSH."
        )
        save_last(result)
        return result

    if has_brew:
        brew = sess.run_script(
            "eval \"$(/opt/homebrew/bin/brew shellenv 2>/dev/null)\"; eval \"$(/usr/local/bin/brew shellenv 2>/dev/null)\"; brew install lan-mouse",
            timeout=180,
        )
        brew_out = (brew.stdout if isinstance(brew.stdout, str) else "") + "\n" + (
            brew.stderr if isinstance(brew.stderr, str) else ""
        )
        result["log"] = _clip(brew_out)
        if brew.returncode == 0:
            result["method"] = "brew"
            result["installed"] = True
            save_last(result)
            return result
        # No formula is common. Fall through to the official zip over SSH.

    zip_url = MAC_ARM if arch == "arm64" else MAC_INTEL
    script = f"""
set -e
tmp=$(mktemp -d)
cd "$tmp"
curl -fsSL -o lm.zip '{zip_url}'
unzip -q lm.zip
app=$(find . -name 'Lan Mouse.app' | head -1)
test -n "$app"
xattr -rd com.apple.quarantine "$app" || true
rm -rf '/Applications/Lan Mouse.app'
mv "$app" /Applications/
echo installed_app
"""
    zip_proc = sess.run_script(script, timeout=180)
    zip_out = (zip_proc.stdout if isinstance(zip_proc.stdout, str) else "") + "\n" + (
        zip_proc.stderr if isinstance(zip_proc.stderr, str) else ""
    )
    result["log"] = _clip(result.get("log", "") + "\n" + zip_out)
    if zip_proc.returncode == 0 and "installed_app" in (zip_proc.stdout or ""):
        result["method"] = "ssh-release"
        result["installed"] = True
    else:
        result["method"] = "manual"
        result["installed"] = False
    save_last(result)
    return result


def install_linux(name: str, peer: dict | None = None, user: str = "", password: str = "") -> dict:
    sess = Session(name, peer, user=user, password=password)
    result = {
        "name": name,
        "os": "Linux",
        "ssh": False,
        "sshVia": "",
        "sshTarget": "",
        "brew": False,
        "method": "manual",
        "installed": False,
        "log": "",
        "instructions": instructions(name, "linux"),
        "needAuth": False,
        "sshUser": sess.user,
        "keyCopied": False,
    }
    probe = sess.run_script("echo ok; command -v pacman; command -v lan-mouse || true", timeout=15)
    stdout = probe.stdout if isinstance(probe.stdout, str) else ""
    stderr = probe.stderr if isinstance(probe.stderr, str) else ""
    result["ssh"] = probe.returncode == 0 and "ok" in stdout
    result["sshVia"] = sess.via
    result["sshTarget"] = sess.target
    result["log"] = _clip(stdout + "\n" + stderr)
    result = _after_ssh(sess, name, password, result["ssh"], result, stdout)
    if not result["ssh"]:
        save_last(result)
        return result
    has_pacman = any(line.rstrip().endswith("pacman") for line in stdout.splitlines())
    if has_pacman:
        inst = sess.run_script("sudo -n pacman -S --needed --noconfirm lan-mouse", timeout=180)
        result["log"] = _clip(
            (inst.stdout if isinstance(inst.stdout, str) else "")
            + "\n"
            + (inst.stderr if isinstance(inst.stderr, str) else "")
        )
        if inst.returncode == 0:
            result["method"] = "pacman"
            result["installed"] = True
            save_last(result)
            return result
    save_last(result)
    return result


def install_windows(name: str) -> dict:
    result = {
        "name": name,
        "os": "Windows",
        "ssh": False,
        "brew": False,
        "method": "manual",
        "installed": False,
        "log": "Windows is installed by hand.",
        "instructions": instructions(name, "windows"),
    }
    save_last(result)
    return result


def install_peer(name: str, user: str = "", password: str = "") -> dict:
    peer = tailscale.find_peer(name)
    if peer is None:
        result = {
            "name": name,
            "os": "",
            "ssh": False,
            "brew": False,
            "method": "manual",
            "installed": False,
            "log": f"no Tailscale machine named {name}",
            "instructions": "",
            "ok": False,
            "error": f"no Tailscale machine named {name}",
            "needAuth": False,
        }
        save_last(result)
        return result
    kind = os_kind(peer.get("os") or "")
    if kind == "mac":
        result = install_mac(name, peer, user=user, password=password)
    elif kind == "linux":
        result = install_linux(name, peer, user=user, password=password)
    elif kind == "windows":
        result = install_windows(name)
    else:
        result = {
            "name": name,
            "os": peer.get("os") or "",
            "ssh": False,
            "brew": False,
            "method": "manual",
            "installed": False,
            "log": "",
            "instructions": instructions(name, peer.get("os") or ""),
        }
        save_last(result)
    result["ok"] = True
    if not result.get("installed") and result.get("method") == "manual":
        result["ok"] = True  # instructions are success of a sort
    return result


def _proc_text(proc) -> tuple[str, str]:
    stdout = proc.stdout if isinstance(proc.stdout, str) else ""
    stderr = proc.stderr if isinstance(proc.stderr, str) else ""
    return stdout, stderr


def retry_ssh(name: str, user: str = "", password: str = "") -> dict:
    """Re-test SSH. If it now works and lan-mouse is not on the peer, install."""
    peer = tailscale.find_peer(name)
    if peer is None:
        result = {
            "name": name,
            "os": "",
            "ssh": False,
            "sshVia": "",
            "sshTarget": "",
            "brew": False,
            "method": "probe",
            "installed": False,
            "log": f"no Tailscale machine named {name}",
            "instructions": "",
            "ok": False,
            "error": f"no Tailscale machine named {name}",
            "needAuth": False,
        }
        save_last(result)
        return result
    kind = os_kind(peer.get("os") or "")
    if kind == "windows":
        result = install_windows(name)
        result["ok"] = True
        return result
    last = load_last()
    sess = Session(name, peer, user=user, password=password)
    probe = sess.run_script(
        "echo ok; whoami; uname -m; "
        "eval \"$(/opt/homebrew/bin/brew shellenv 2>/dev/null)\"; "
        "eval \"$(/usr/local/bin/brew shellenv 2>/dev/null)\"; "
        "command -v brew || true; echo ---; "
        "test -d '/Applications/Lan Mouse.app' && echo app_present || true; "
        "command -v lan-mouse && echo bin_present || true",
        timeout=15,
    )
    stdout, stderr = _proc_text(probe)
    ssh_ok = probe.returncode == 0 and "ok" in stdout
    present = "app_present" in stdout or "bin_present" in stdout
    already = present or (last.get("name") == name and bool(last.get("installed")))
    result = {
        "name": name,
        "os": peer.get("os") or "",
        "ssh": ssh_ok,
        "sshVia": sess.via,
        "sshTarget": sess.target,
        "brew": any(line.rstrip().endswith("brew") for line in stdout.splitlines()),
        "method": "probe",
        "installed": already and ssh_ok,
        "log": _clip(stdout + "\n" + stderr),
        "instructions": "",
        "ok": True,
        "needAuth": False,
        "sshUser": sess.user,
        "keyCopied": False,
    }
    result = _after_ssh(sess, name, password, ssh_ok, result, stdout)
    if not ssh_ok:
        result["method"] = "manual"
        result["installed"] = False
        result["instructions"] = instructions(name, peer.get("os") or "")
        result["log"] = _clip(
            (stdout + "\n" + stderr).strip()
            or "SSH did not connect. Enter the SSH user and password for that machine, then Retry SSH."
        )
        save_last(result)
        return result
    if already:
        via = sess.via or "ssh"
        target = sess.target or name
        who = result.get("sshUser") or sess.user or name
        extra = " Copied this computer's SSH key." if result.get("keyCopied") else ""
        result["log"] = _clip(f"SSH works ({via} {who}@{target}). lan-mouse is already on {name}.{extra}")
        result["installed"] = True
        result["method"] = last.get("method") if last.get("name") == name and last.get("method") not in ("", "manual", "probe") else "probe"
        save_last(result)
        return result
    return install_peer(name, user=user or sess.user, password=password)


def _return_edge(position: str) -> str:
    return {
        "left": "right",
        "right": "left",
        "top": "bottom",
        "bottom": "top",
    }.get(position or "right", "left")


def pair_peer(
    name: str,
    peer: dict | None,
    *,
    user: str = "",
    password: str = "",
    local_fp: str = "",
    local_name: str = "",
    local_ip: str = "",
    local_position: str = "right",
) -> dict:
    """Start lan-mouse on the peer and exchange fingerprints over SSH."""
    if peer is None:
        return {"paired": False, "log": f"no Tailscale machine named {name}"}
    if not local_fp:
        return {
            "paired": False,
            "log": "Start lan-mouse on this computer first so we have a fingerprint to share.",
        }
    sess = Session(name, peer, user=user, password=password)
    local_name = local_name or "dirk"
    ret = _return_edge(local_position)
    toml = (
        "port = 4242\n"
        'release_bind = ["KeyLeftCtrl", "KeyLeftShift", "KeyLeftMeta", "KeyLeftAlt"]\n'
        "\n"
        "[authorized_fingerprints]\n"
        f'"{local_fp}" = "{local_name}"\n'
        "\n"
        "[[clients]]\n"
        f'hostname = "{local_name}"\n'
        f'position = "{ret}"\n'
        f'ips = ["{local_ip}"]\n'
        "port = 4242\n"
        "activate_on_startup = true\n"
    )
    quoted = shlex.quote(toml.rstrip())
    kind = os_kind(peer.get("os") or "")
    # The Mac GUI can blank authorized_fingerprints. Start it in the login
    # graphical session (SSH-started `daemon` uses the dummy backend and
    # never moves the cursor), then write the config again after it maps.
    if kind == "mac":
        script = f"""
set -e
killall lan-mouse 2>/dev/null || true
sleep 0.3
mkdir -p "$HOME/.config/lan-mouse"
printf '%s\\n' {quoted} > "$HOME/.config/lan-mouse/config.toml"
open -a "Lan Mouse"
i=0
while [ "$i" -lt 20 ]; do
  if pgrep -x lan-mouse >/dev/null 2>&1; then
    break
  fi
  i=$((i + 1))
  sleep 0.2
done
sleep 0.6
printf '%s\\n' {quoted} > "$HOME/.config/lan-mouse/config.toml"
pem="$HOME/.config/lan-mouse/lan-mouse.pem"
i=0
while [ "$i" -lt 25 ]; do
  if [ -f "$pem" ]; then
    openssl x509 -in "$pem" -noout -fingerprint -sha256
    grep -q {shlex.quote(local_fp)} "$HOME/.config/lan-mouse/config.toml" || {{ echo config_clobbered; exit 2; }}
    exit 0
  fi
  i=$((i + 1))
  sleep 0.2
done
echo no_cert
exit 1
"""
    else:
        script = f"""
set -e
pkill -x lan-mouse 2>/dev/null || true
sleep 0.2
mkdir -p "$HOME/.config/lan-mouse"
printf '%s\\n' {quoted} > "$HOME/.config/lan-mouse/config.toml"
if command -v lan-mouse >/dev/null; then
  nohup lan-mouse daemon >/tmp/lan-mouse.log 2>&1 &
fi
sleep 0.4
printf '%s\\n' {quoted} > "$HOME/.config/lan-mouse/config.toml"
pem="$HOME/.config/lan-mouse/lan-mouse.pem"
i=0
while [ "$i" -lt 25 ]; do
  if [ -f "$pem" ]; then
    openssl x509 -in "$pem" -noout -fingerprint -sha256
    exit 0
  fi
  i=$((i + 1))
  sleep 0.2
done
echo no_cert
exit 1
"""
    started = sess.run_script(script, timeout=25)
    stdout, stderr = _proc_text(started)
    out = (stdout + "\n" + stderr).strip()
    fp = ""
    if started.returncode == 0 and "=" in stdout:
        fp = stdout.strip().split("=", 1)[1].strip().lower()
    if "config_clobbered" in out:
        return {
            "paired": False,
            "remoteStarted": True,
            "log": _clip("lan-mouse on that Mac overwrote the pairing. Close the Lan Mouse window there, then Re-pair."),
        }
    if not fp:
        hint = " Grant Accessibility on that Mac if it asks, then Re-pair."
        return {
            "paired": False,
            "remoteStarted": "no_cert" in out or started.returncode != 0,
            "log": _clip(out + (hint if kind == "mac" else "")),
        }
    return {
        "paired": True,
        "remoteFingerprint": fp,
        "remoteStarted": True,
        "returnEdge": ret,
        "log": (
            f"Paired with {name}. Fingerprint {fp}. "
            f"Off this {local_position or 'edge'} goes there. "
            f"Off {name}'s {ret} comes back here. "
            "While the pointer is on this machine, that computer's mouse is captured; "
            "slide back to the facing edge or press Control+Shift+Alt+Super to release."
        ),
    }


def copy_instructions(name: str = "") -> dict:
    last = load_last()
    text = ""
    if name and last.get("name") == name:
        text = last.get("instructions") or ""
    if not text:
        peer = tailscale.find_peer(name) if name else None
        if peer:
            text = instructions(name, peer.get("os") or "")
        elif last.get("instructions"):
            text = last["instructions"]
    if not text:
        return {"ok": False, "error": "no instructions to copy"}
    import shutil
    import subprocess

    if shutil.which("wl-copy"):
        subprocess.run(["wl-copy"], input=(text + "\n").encode(), check=False, timeout=2)
    return {"ok": True, "copied": True, "instructions": text}
