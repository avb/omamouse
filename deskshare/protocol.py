from __future__ import annotations

import json
import struct
from typing import Any

MAX_FRAME = 256 * 1024
HEADER = struct.Struct("!I")


def encode(msg: dict[str, Any]) -> bytes:
    payload = json.dumps(msg, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_FRAME:
        raise ValueError("frame too large")
    return HEADER.pack(len(payload)) + payload


def read_frame(sock) -> dict[str, Any] | None:
    header = _recv_exact(sock, 4)
    if header is None:
        return None
    (length,) = HEADER.unpack(header)
    if length <= 0 or length > MAX_FRAME:
        raise ValueError("bad frame length")
    payload = _recv_exact(sock, length)
    if payload is None:
        return None
    data = json.loads(payload.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("frame is not an object")
    return data


def _recv_exact(sock, n: int) -> bytes | None:
    chunks = []
    got = 0
    while got < n:
        piece = sock.recv(n - got)
        if not piece:
            return None
        chunks.append(piece)
        got += len(piece)
    return b"".join(chunks)
