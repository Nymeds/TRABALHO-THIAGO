import json
import socket
import struct
from typing import Any, Dict, Optional

_MAX_PACKET_SIZE = 1024 * 1024


def _recv_exact(sock: socket.socket, size: int) -> Optional[bytes]:
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            return None
        data.extend(chunk)
    return bytes(data)


def send_packet(sock: socket.socket, payload: Dict[str, Any]) -> None:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    header = struct.pack("!I", len(body))
    sock.sendall(header + body)


def recv_packet(sock: socket.socket) -> Optional[Dict[str, Any]]:
    header = _recv_exact(sock, 4)
    if header is None:
        return None

    (length,) = struct.unpack("!I", header)
    if length > _MAX_PACKET_SIZE:
        raise ValueError("packet too large")

    body = _recv_exact(sock, length)
    if body is None:
        return None

    return json.loads(body.decode("utf-8"))
