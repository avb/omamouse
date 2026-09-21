"""Run a command on a Tailscale peer.

Classic OpenSSH uses Tailscale addresses, with DNS names as fallbacks.
New host keys use OpenSSH's accept-new policy; changed keys are rejected.

A username is remembered per peer. A password is never stored. When one is
supplied for this attempt, OpenSSH gets it through ASKPASS, then we copy this
computer's public key onto the peer so the next login can use the key.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from . import paths


def _targets(host: str, peer: dict | None) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        value = (value or "").strip().rstrip(".")
        if value and value not in seen:
            seen.add(value)
            names.append(value)

    if peer:
        for ip in peer.get("ips") or []:
            add(str(ip))
        add(str(peer.get("dnsName") or ""))
        add(str(peer.get("name") or ""))
    add(host)
    return names


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
    paths.atomic_write(paths.SSH_USERS_PATH, json.dumps(data, indent=2) + "\n")
    paths.SSH_USERS_PATH.chmod(0o600)


def _stderr_text(proc: subprocess.CompletedProcess[Any]) -> str:
    err = proc.stderr
    if isinstance(err, bytes):
        return err.decode("utf-8", "replace")
    return err or ""


def _is_auth_failure(text: str) -> bool:
    t = text.lower()
    return "permission denied" in t or "authentication failed" in t or "invalid user" in t


def _askpass_env(password: str) -> tuple[dict[str, str], Path | None]:
    env = os.environ.copy()
    if not password:
        return env, None
    paths.ensure()
    fd, name = tempfile.mkstemp(prefix="ssh-pass-", dir=paths.RUNTIME_DIR)
    passfile = Path(name)
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
    cmd += ["--", dest, remote]
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

    def run(
        self,
        argv: list[str],
        *,
        timeout: float = 20.0,
        input: str | bytes | None = None,
    ) -> subprocess.CompletedProcess[Any]:
        text_mode = not isinstance(input, (bytes, bytearray))
        if self.target:
            return self._one(self.target, argv, timeout, input, text_mode)

        last: subprocess.CompletedProcess[Any] | None = None
        for target in _targets(self.host, self.peer):
            proc = self._one(target, argv, timeout, input, text_mode)
            last = proc
            if _is_auth_failure(_stderr_text(proc)):
                return proc
            # A timeout may follow a successful remote mutation. Never replay it.
            if proc.returncode == 255 and any(message in _stderr_text(proc).lower() for message in (
                "could not resolve hostname", "connection refused", "no route to host",
                "network is unreachable", "connection timed out",
            )):
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
