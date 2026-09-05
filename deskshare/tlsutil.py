from __future__ import annotations

import hashlib
import ssl
import subprocess
from pathlib import Path

from .paths import CERT_PATH, KEY_PATH, ensure


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, capture_output=True, text=True)


def ensure_cert() -> None:
    ensure()
    if CERT_PATH.exists() and KEY_PATH.exists():
        return
    proc = _run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "ec",
            "-pkeyopt",
            "ec_paramgen_curve:P-256",
            "-days",
            "3650",
            "-nodes",
            "-keyout",
            str(KEY_PATH),
            "-out",
            str(CERT_PATH),
            "-subj",
            "/CN=deskshare",
        ]
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "openssl failed").strip())
    CERT_PATH.chmod(0o644)
    KEY_PATH.chmod(0o600)


def fingerprint() -> str:
    ensure_cert()
    proc = _run(["openssl", "x509", "-in", str(CERT_PATH), "-noout", "-fingerprint", "-sha256"])
    if proc.returncode != 0:
        raise RuntimeError("could not read TLS fingerprint")
    return proc.stdout.strip().split("=", 1)[-1].strip().lower()


def fingerprint_bytes(der: bytes) -> str:
    digest = hashlib.sha256(der).hexdigest()
    return ":".join(digest[i : i + 2] for i in range(0, len(digest), 2))


def server_context() -> ssl.SSLContext:
    ensure_cert()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(CERT_PATH), str(KEY_PATH))
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def client_context() -> ssl.SSLContext:
    ensure_cert()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.load_cert_chain(str(CERT_PATH), str(KEY_PATH))
    return ctx


def peer_fingerprint(ssock: ssl.SSLSocket) -> str:
    der = ssock.getpeercert(binary_form=True) or b""
    if not der:
        return ""
    return fingerprint_bytes(der)
