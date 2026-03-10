import json
import socket
import struct
from typing import Any, Dict, Optional

_MAX_PACKET_SIZE = 1024 * 1024


# //Socket TCP e stream de bytes, entao mensagem pode chegar fragmentada.
# //Essa funcao garante leitura EXATA de N bytes antes de continuar.
def _recv_exact(sock: socket.socket, size: int) -> Optional[bytes]:
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            return None
        data.extend(chunk)
    return bytes(data)

# //Aqui esta o "framing" da aplicacao: [4 bytes tamanho][JSON UTF-8].
# //Todo envio cliente<->servidor passa por este ponto.
def send_packet(sock: socket.socket, payload: Dict[str, Any]) -> None:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    header = struct.pack("!I", len(body))
    sock.sendall(header + body)

# // Le primeiro o cabecalho de 4 bytes, descobre o tamanho e so depois le o corpo.
# // Sem isso, o receptor nao sabe onde uma mensagem termina e a proxima comeca.
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
