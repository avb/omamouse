from __future__ import annotations

import json
import subprocess

from . import paths, tailscale

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
            "Optional, so this panel can install it next time: Tailscale menu, SSH, On.\n"
            "If Homebrew is installed we will try `brew install lan-mouse` over Tailscale SSH."
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


def _ssh(host: str, script: str, timeout: float = 20.0) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["tailscale", "ssh", host, "--", "bash", "-lc", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(["tailscale"], 127, "", "tailscale not found")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(["tailscale"], 124, "", "ssh timed out")


def ssh_available(host: str) -> bool:
    proc = _ssh(host, "echo ok", timeout=12)
    return proc.returncode == 0 and "ok" in (proc.stdout or "")


def _clip(text: str, limit: int = 800) -> str:
    text = (text or "").strip()
    if len(text) > limit:
        return text[:limit] + "…"
    return text


def install_mac(name: str) -> dict:
    probe = _ssh(
        name,
        "eval \"$(/opt/homebrew/bin/brew shellenv 2>/dev/null)\"; eval \"$(/usr/local/bin/brew shellenv 2>/dev/null)\"; command -v brew; uname -m; echo ---; test -d '/Applications/Lan Mouse.app' && echo app_present || true",
        timeout=15,
    )
    ssh_ok = probe.returncode == 0
    out = (probe.stdout or "") + (probe.stderr or "")
    has_brew = ssh_ok and any(line.rstrip().endswith("brew") for line in probe.stdout.splitlines())
    arch = "arm64"
    for line in probe.stdout.splitlines():
        if line.strip() in ("arm64", "x86_64"):
            arch = line.strip()
    result = {
        "name": name,
        "os": "macOS",
        "ssh": ssh_ok,
        "brew": has_brew,
        "method": "manual",
        "installed": False,
        "log": _clip(out),
        "instructions": instructions(name, "macOS"),
    }
    if not ssh_ok:
        result["log"] = _clip(out or "Tailscale SSH did not connect. Enable SSH on that Mac (Tailscale menu) or install by hand.")
        save_last(result)
        return result

    if has_brew:
        brew = _ssh(
            name,
            "eval \"$(/opt/homebrew/bin/brew shellenv 2>/dev/null)\"; eval \"$(/usr/local/bin/brew shellenv 2>/dev/null)\"; brew install lan-mouse",
            timeout=180,
        )
        result["log"] = _clip((brew.stdout or "") + "\n" + (brew.stderr or ""))
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
    zip_proc = _ssh(name, script, timeout=180)
    result["log"] = _clip(result.get("log", "") + "\n" + (zip_proc.stdout or "") + "\n" + (zip_proc.stderr or ""))
    if zip_proc.returncode == 0 and "installed_app" in (zip_proc.stdout or ""):
        result["method"] = "ssh-release"
        result["installed"] = True
    else:
        result["method"] = "manual"
        result["installed"] = False
    save_last(result)
    return result


def install_linux(name: str) -> dict:
    result = {
        "name": name,
        "os": "Linux",
        "ssh": False,
        "brew": False,
        "method": "manual",
        "installed": False,
        "log": "",
        "instructions": instructions(name, "linux"),
    }
    probe = _ssh(name, "echo ok; command -v pacman; command -v lan-mouse || true", timeout=15)
    result["ssh"] = probe.returncode == 0 and "ok" in (probe.stdout or "")
    result["log"] = _clip((probe.stdout or "") + "\n" + (probe.stderr or ""))
    if not result["ssh"]:
        save_last(result)
        return result
    has_pacman = any(line.rstrip().endswith("pacman") for line in probe.stdout.splitlines())
    if has_pacman:
        inst = _ssh(name, "sudo -n pacman -S --needed --noconfirm lan-mouse", timeout=180)
        result["log"] = _clip((inst.stdout or "") + "\n" + (inst.stderr or ""))
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


def install_peer(name: str) -> dict:
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
        }
        save_last(result)
        return result
    kind = os_kind(peer.get("os") or "")
    if kind == "mac":
        result = install_mac(name)
    elif kind == "linux":
        result = install_linux(name)
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
