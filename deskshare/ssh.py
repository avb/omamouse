"""Run a command on a Tailscale peer.

Classic OpenSSH is used against the short Tailscale hostname (spatha, not
spatha.taild30dae.ts.net), then the Tailscale IPv4 if that name does not
connect. Host keys are fetched with ssh-keyscan over Tailscale and accepted
automatically. That is safe here because the path is already the tailnet.

A username is remembered per peer. A password is never stored. When one is
supplied for this attempt, OpenSSH gets it through ASKPASS, then we copy this
computer's public key onto the peer so the next login can use the key.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

from . import paths


def _short_name(value: str) -> str:
    value = (value or "").strip().rstrip(".")
    if not value or _looks_ip(value):
        return value
    return value.split(".", 1)[0]


def _targets(host: str, peer: dict | None) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        value = (value or "").strip().rstrip(".")
        if value and value not in seen:
            seen.add(value)
            names.append(value)

    add(_short_name(host))
    if peer:
        add(_short_name(str(peer.get("name") or "")))
        add(_short_name(str(peer.get("dnsName") or "")))
        for ip in peer.get("ips") or []:
            add(str(ip))
    return names


def _looks_ip(value: str) -> bool:
    parts = value.split(".")
    return len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts if p)


def _connect_timeout(timeout: float) -> str:
    return str(max(2, min(8, int(timeout) - 1 if timeout >= 3 else int(timeout))))


def _known_hosts() -> Path:
    paths.ensure()
    path = paths.KNOWN_HOSTS_PATH
    if not path.exists():
        path.touch(mode=0o600)
    return path


def load_users() -> dict[str, str]:
    paths.ensure()
    if not paths.SSH_USERS_PATH.exists():
        return {}
    try:
        data = json.loads(paths.SSH_USERS_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if str(k) and str(v)}


def load_user(host: str) -> str:
    return load_users().get(host, "")


def save_user(host: str, user: str) -> None:
    host = (host or "").strip()
    user = (user or "").strip()
    if not host or not user:
        return
    data = load_users()
    data[host] = user
    paths.ensure()
    paths.SSH_USERS_PATH.write_text(json.dumps(data, indent=2) + "\n")
    paths.SSH_USERS_PATH.chmod(0o600)


def _stderr_text(proc: subprocess.CompletedProcess[Any]) -> str:
    err = proc.stderr
    if isinstance(err, bytes):
        return err.decode("utf-8", "replace")
    return err or ""


def _is_auth_failure(text: str) -> bool:
    t = text.lower()
    return "permission denied" in t or "authentication failed" in t or "invalid user" in t


def trust_host_keys(host: str, peer: dict | None) -> None:
    """Record the peer's SSH host key under every Tailscale name we use."""
    names = _targets(host, peer)
    if not names:
        return
    scan_from = [n for n in names if _looks_ip(n)] or names
    scanned: list[tuple[str, str]] = []
    for target in scan_from:
        try:
            proc = subprocess.run(
                ["ssh-keyscan", "-T", "4", "-t", "ed25519,ecdsa,rsa", target],
                check=False,
                capture_output=True,
                text=True,
                timeout=8,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 3:
                scanned.append((parts[1], parts[2]))
        if scanned:
            break
    if not scanned:
        return
    path = _known_hosts()
    existing = path.read_text() if path.exists() else ""
    aliases = ",".join(names)
    added = False
    with path.open("a") as handle:
        for key_type, blob in scanned:
            needle = f"{key_type} {blob}"
            already = any(
                needle in line and all(name in line.split()[0].split(",") for name in names)
                for line in existing.splitlines()
                if line.strip() and not line.startswith("#")
            )
            if already:
                continue
            handle.write(f"{aliases} {key_type} {blob}\n")
            added = True
    if added:
        path.chmod(0o600)


def _askpass_env(password: str) -> tuple[dict[str, str], Path | None]:
    env = os.environ.copy()
    if not password:
        return env, None
    paths.ensure()
    passfile = paths.RUNTIME_DIR / "ssh-pass"
    fd = os.open(str(passfile), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(password)
    askpass = paths.PLUGIN_ROOT / "scripts" / "ssh-askpass"
    if askpass.exists() and not os.access(askpass, os.X_OK):
        askpass.chmod(0o700)
    env["SSH_ASKPASS"] = str(askpass)
    env["SSH_ASKPASS_REQUIRE"] = "force"
    env["DESKSHARE_SSH_PASSFILE"] = str(passfile)
    env.setdefault("DISPLAY", ":0")
    return env, passfile


def _clear_passfile(path: Path | None) -> None:
    if path is None:
        return
    try:
        if path.exists():
            path.write_text("")
            path.unlink()
    except OSError:
        pass


def _cmd(target: str, argv: list[str], timeout: float, user: str = "", password: str = "") -> list[str]:
    # One remote string so the peer's login shell (zsh on macOS) does not
    # resplit `bash -c` from its script.
    remote = " ".join(shlex.quote(part) for part in argv)
    dest = f"{user}@{target}" if user else target
    cmd = [
        "ssh",
        "-o", f"ConnectTimeout={_connect_timeout(timeout)}",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "UpdateHostKeys=yes",
        "-o", "CheckHostIP=no",
        "-o", "HashKnownHosts=no",
        "-o", f"UserKnownHostsFile={_known_hosts()}",
        "-o", "GlobalKnownHostsFile=/dev/null",
    ]
    if password:
        cmd += [
            "-o", "PreferredAuthentications=password,keyboard-interactive",
            "-o", "PubkeyAuthentication=no",
            "-o", "PasswordAuthentication=yes",
            "-o", "KbdInteractiveAuthentication=yes",
            "-o", "NumberOfPasswordPrompts=1",
        ]
    else:
        cmd += ["-o", "BatchMode=yes"]
    cmd += [dest, "--", remote]
    return cmd


def local_public_key() -> str:
    for name in ("id_ed25519.pub", "id_rsa.pub", "id_ecdsa.pub"):
        pub = Path.home() / ".ssh" / name
        if pub.is_file():
            key = pub.read_text().strip()
            if key:
                return key
    return ""


def install_login_key(sess: Session) -> bool:
    key = local_public_key()
    if not key:
        return False
    script = f"""
set -e
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
touch "$HOME/.ssh/authorized_keys"
chmod 600 "$HOME/.ssh/authorized_keys"
if ! grep -qxF {shlex.quote(key)} "$HOME/.ssh/authorized_keys" 2>/dev/null; then
  printf '%s\\n' {shlex.quote(key)} >> "$HOME/.ssh/authorized_keys"
fi
echo key_installed
"""
    proc = sess.run_script(script, timeout=12)
    return proc.returncode == 0 and "key_installed" in (proc.stdout or "")


class Session:
    def __init__(self, host: str, peer: dict | None = None, user: str = "", password: str = "") -> None:
        self.host = host
        self.peer = peer
        self.user = (user or "").strip() or load_user(host)
        self.password = password or ""
        self.target = ""
        self.via = "ssh"
        self.last: subprocess.CompletedProcess[Any] | None = None
        self._trusted = False

    def run(
        self,
        argv: list[str],
        *,
        timeout: float = 20.0,
        input: str | bytes | None = None,
    ) -> subprocess.CompletedProcess[Any]:
        text_mode = not isinstance(input, (bytes, bytearray))
        if not self._trusted:
            trust_host_keys(self.host, self.peer)
            self._trusted = True
        if self.target:
            return self._one(self.target, argv, timeout, input, text_mode)

        last: subprocess.CompletedProcess[Any] | None = None
        for target in _targets(self.host, self.peer):
            proc = self._one(target, argv, timeout, input, text_mode)
            last = proc
            if _is_auth_failure(_stderr_text(proc)):
                return proc
            if proc.returncode in (255, 124, 127):
                continue
            self.target = target
            return proc
        self.last = last
        return last or subprocess.CompletedProcess(["ssh"], 255, "", "no ssh target")

    def run_script(self, script: str, timeout: float = 20.0) -> subprocess.CompletedProcess[str]:
        proc = self.run(["bash", "-c", script], timeout=timeout)
        return proc  # type: ignore[return-value]

    def _one(
        self,
        target: str,
        argv: list[str],
        timeout: float,
        input: str | bytes | None,
        text_mode: bool,
    ) -> subprocess.CompletedProcess[Any]:
        cmd = _cmd(target, argv, timeout, user=self.user, password=self.password)
        env, passfile = _askpass_env(self.password)
        try:
            proc = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=text_mode,
                input=input,
                timeout=timeout,
                env=env,
            )
        except FileNotFoundError:
            proc = subprocess.CompletedProcess(cmd, 127, "" if text_mode else b"", "not found" if text_mode else b"not found")
        except subprocess.TimeoutExpired:
            msg = f"ssh to {target} timed out"
            proc = subprocess.CompletedProcess(cmd, 124, "" if text_mode else b"", msg if text_mode else msg.encode())
        finally:
            _clear_passfile(passfile)
        self.last = proc
        if proc.returncode == 0:
            self.target = target
        return proc
