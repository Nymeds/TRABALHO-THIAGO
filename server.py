import argparse
import hashlib
import json
import os
import re
import socket
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from crypto_utils import decrypt_text, encrypt_text
from protocol import recv_packet, send_packet


@dataclass
class ClientSession:
    name: str
    address: Tuple[str, int]
    room: Optional[str] = None


clients: Dict[socket.socket, ClientSession] = {}
rooms: Dict[str, Set[socket.socket]] = {}
state_lock = threading.Lock()
history_lock = threading.Lock()

HISTORY_DIR = Path("storage") / "history"
MAX_ROOM_HISTORY = 120


def sanitize_name(raw_name: object) -> str:
    name = str(raw_name or "").strip()
    if not name:
        return "Anonimo"
    return name[:24]


def sanitize_room(raw_room: object) -> str:
    room = str(raw_room or "").strip()
    return room[:32]


def ensure_history_dir() -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def history_file_for_room(room_name: str) -> Path:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", room_name.strip()).strip("-").lower()
    if not slug:
        slug = "sala"
    room_hash = hashlib.sha1(room_name.encode("utf-8")).hexdigest()[:10]
    return HISTORY_DIR / f"{slug}_{room_hash}.jsonl"


def is_valid_encrypted_payload(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    required_fields = ("nonce", "ciphertext", "tag")
    return all(field in payload and isinstance(payload[field], str) for field in required_fields)


def persist_room_message(room_name: str, sender: str, payload: dict) -> None:
    if not is_valid_encrypted_payload(payload):
        return

    ensure_history_dir()
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "sender": sender,
        "payload": payload,
    }
    file_path = history_file_for_room(room_name)

    with history_lock:
        with file_path.open("a", encoding="utf-8") as history_file:
            history_file.write(json.dumps(entry, separators=(",", ":"), ensure_ascii=False))
            history_file.write("\n")


def load_room_history(room_name: str, limit: int = MAX_ROOM_HISTORY) -> List[dict]:
    file_path = history_file_for_room(room_name)
    if not file_path.exists():
        return []

    entries: List[dict] = []
    with history_lock:
        with file_path.open("r", encoding="utf-8") as history_file:
            for line in history_file:
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    continue

                sender = str(parsed.get("sender", ""))
                payload = parsed.get("payload")
                if sender and is_valid_encrypted_payload(payload):
                    entries.append(
                        {
                            "ts": str(parsed.get("ts", "")),
                            "sender": sender,
                            "payload": payload,
                        }
                    )

    if limit <= 0:
        return []
    return entries[-limit:]


def get_local_ipv4_addresses() -> List[str]:
    addresses: Set[str] = set()

    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM):
            ip = info[4][0]
            if ip and not ip.startswith("127."):
                addresses.add(ip)
    except OSError:
        pass

    try:
        # Nao envia trafego; apenas descobre o IP local preferencial da interface de saida.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            ip = probe.getsockname()[0]
            if ip and not ip.startswith("127."):
                addresses.add(ip)
    except OSError:
        pass

    return sorted(addresses)


def safe_send(conn: socket.socket, packet: dict) -> bool:
    try:
        send_packet(conn, packet)
        return True
    except OSError:
        return False


def get_session(conn: socket.socket) -> Optional[ClientSession]:
    with state_lock:
        return clients.get(conn)


def get_room_snapshot() -> List[dict]:
    with state_lock:
        snapshot = [
            {"name": room_name, "users": len(members)}
            for room_name, members in sorted(rooms.items())
            if members
        ]
    return snapshot


def broadcast_room_list() -> None:
    packet = {"type": "room_list", "rooms": get_room_snapshot()}
    with state_lock:
        conns = list(clients.keys())

    disconnected: List[socket.socket] = []
    for conn in conns:
        if not safe_send(conn, packet):
            disconnected.append(conn)

    for conn in disconnected:
        handle_disconnect(conn)


def get_room_members(room_name: str) -> List[socket.socket]:
    with state_lock:
        return list(rooms.get(room_name, set()))


def broadcast_encrypted(room_name: str, sender: str, text: str, shared_secret: str) -> None:
    packet = {
        "type": "broadcast",
        "room": room_name,
        "from": sender,
        "payload": encrypt_text(text, shared_secret),
    }

    disconnected: List[socket.socket] = []
    for conn in get_room_members(room_name):
        if not safe_send(conn, packet):
            disconnected.append(conn)

    for conn in disconnected:
        handle_disconnect(conn)


def broadcast_payload(room_name: str, sender: str, payload: dict) -> None:
    packet = {
        "type": "broadcast",
        "room": room_name,
        "from": sender,
        "payload": payload,
    }

    disconnected: List[socket.socket] = []
    for conn in get_room_members(room_name):
        if not safe_send(conn, packet):
            disconnected.append(conn)

    for conn in disconnected:
        handle_disconnect(conn)


def move_client_to_room(conn: socket.socket, new_room: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    with state_lock:
        session = clients.get(conn)
        if session is None:
            return None, None, None

        if new_room not in rooms:
            rooms[new_room] = set()

        old_room = session.room
        if old_room == new_room:
            return session.name, old_room, new_room

        if old_room:
            old_members = rooms.get(old_room)
            if old_members is not None:
                old_members.discard(conn)
                if not old_members:
                    rooms.pop(old_room, None)

        rooms[new_room].add(conn)
        session.room = new_room
        return session.name, old_room, new_room


def leave_current_room(conn: socket.socket) -> Tuple[Optional[str], Optional[str]]:
    with state_lock:
        session = clients.get(conn)
        if session is None or session.room is None:
            return None, None

        room_name = session.room
        members = rooms.get(room_name)
        if members is not None:
            members.discard(conn)
            if not members:
                rooms.pop(room_name, None)

        session.room = None
        return session.name, room_name


def handle_disconnect(conn: socket.socket) -> Tuple[Optional[str], Optional[str]]:
    with state_lock:
        session = clients.pop(conn, None)
        if session is None:
            return None, None

        room_name = session.room
        if room_name is not None:
            members = rooms.get(room_name)
            if members is not None:
                members.discard(conn)
                if not members:
                    rooms.pop(room_name, None)

    try:
        conn.close()
    except OSError:
        pass

    if session.name:
        print(f"[-] {session.name} desconectou")

    broadcast_room_list()
    if room_name:
        return session.name, room_name
    return session.name, None


def process_message_packet(conn: socket.socket, packet: dict, shared_secret: str) -> None:
    session = get_session(conn)
    if session is None:
        return

    if session.room is None:
        safe_send(conn, {"type": "error", "text": "Entre em uma sala antes de enviar mensagens."})
        return

    payload = packet.get("payload")
    if not isinstance(payload, dict):
        safe_send(conn, {"type": "error", "text": "Payload de mensagem invalido."})
        return

    try:
        # Valida autenticidade/integridade sem exibir o texto em claro no servidor.
        decrypt_text(payload, shared_secret)
    except ValueError:
        print(f"[!] Mensagem invalida de {session.name}: falha de autenticacao.")
        safe_send(conn, {"type": "error", "text": "Falha de autenticacao da mensagem."})
        return

    print(f"[{session.room}] [{session.name}] payload_criptografado={payload}")
    persist_room_message(session.room, session.name, payload)
    broadcast_payload(session.room, session.name, payload)


def process_create_room(conn: socket.socket, packet: dict, shared_secret: str) -> None:
    room_name = sanitize_room(packet.get("room"))
    if not room_name:
        safe_send(conn, {"type": "error", "text": "Nome da sala invalido."})
        return

    session_name, old_room, new_room = move_client_to_room(conn, room_name)
    if session_name is None or new_room is None:
        return

    safe_send(conn, {"type": "joined_room", "room": new_room})
    safe_send(conn, {"type": "room_history", "room": new_room, "messages": load_room_history(new_room)})
    broadcast_room_list()

    if old_room and old_room != new_room:
        broadcast_encrypted(old_room, "Servidor", f"{session_name} saiu da sala.", shared_secret)
    broadcast_encrypted(new_room, "Servidor", f"{session_name} entrou na sala.", shared_secret)


def process_join_room(conn: socket.socket, packet: dict, shared_secret: str) -> None:
    room_name = sanitize_room(packet.get("room"))
    if not room_name:
        safe_send(conn, {"type": "error", "text": "Nome da sala invalido."})
        return

    with state_lock:
        exists = room_name in rooms and bool(rooms[room_name])

    if not exists:
        safe_send(conn, {"type": "error", "text": "Sala nao encontrada."})
        return

    session_name, old_room, new_room = move_client_to_room(conn, room_name)
    if session_name is None or new_room is None:
        return

    safe_send(conn, {"type": "joined_room", "room": new_room})
    safe_send(conn, {"type": "room_history", "room": new_room, "messages": load_room_history(new_room)})
    broadcast_room_list()

    if old_room and old_room != new_room:
        broadcast_encrypted(old_room, "Servidor", f"{session_name} saiu da sala.", shared_secret)
    broadcast_encrypted(new_room, "Servidor", f"{session_name} entrou na sala.", shared_secret)


def process_leave_room(conn: socket.socket, shared_secret: str) -> None:
    session_name, old_room = leave_current_room(conn)
    if session_name is None:
        return

    safe_send(conn, {"type": "left_room"})
    broadcast_room_list()
    if old_room:
        broadcast_encrypted(old_room, "Servidor", f"{session_name} saiu da sala.", shared_secret)


def handle_client(conn: socket.socket, address: Tuple[str, int], shared_secret: str) -> None:
    client_name: Optional[str] = None

    try:
        hello_packet = recv_packet(conn)
        if hello_packet is None or hello_packet.get("type") != "hello":
            safe_send(conn, {"type": "error", "text": "Handshake invalido."})
            return

        client_name = sanitize_name(hello_packet.get("name"))
        with state_lock:
            clients[conn] = ClientSession(name=client_name, address=address)

        print(f"[+] {client_name} conectado de {address[0]}:{address[1]}")
        safe_send(conn, {"type": "hello_ack", "name": client_name, "rooms": get_room_snapshot()})
        broadcast_room_list()

        while True:
            packet = recv_packet(conn)
            if packet is None:
                break

            packet_type = packet.get("type")
            if packet_type == "list_rooms":
                safe_send(conn, {"type": "room_list", "rooms": get_room_snapshot()})
            elif packet_type == "create_room":
                process_create_room(conn, packet, shared_secret)
            elif packet_type == "join_room":
                process_join_room(conn, packet, shared_secret)
            elif packet_type == "leave_room":
                process_leave_room(conn, shared_secret)
            elif packet_type == "message":
                process_message_packet(conn, packet, shared_secret)
            else:
                safe_send(conn, {"type": "error", "text": "Comando desconhecido."})

    except (ConnectionError, OSError, ValueError):
        pass
    finally:
        name, room_name = handle_disconnect(conn)
        if name and room_name:
            broadcast_encrypted(room_name, "Servidor", f"{name} saiu da sala.", shared_secret)


def run_server(host: str, port: int, shared_secret: str) -> None:
    ensure_history_dir()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_sock:
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind((host, port))
        server_sock.listen()

        print(f"Servidor ouvindo em {host}:{port}")
        print(f"Historico criptografado: {HISTORY_DIR.resolve()}")
        if host == "0.0.0.0":
            ips = get_local_ipv4_addresses()
            if ips:
                print("Identificador(es) para clientes na rede local:")
                for ip in ips:
                    print(f"  - {ip}:{port}")
            else:
                print("Nao foi possivel detectar IP local automaticamente.")
                print(f"Use manualmente o IP da sua maquina com a porta {port}.")

        if shared_secret == "troque-esta-chave":
            print("[!] Aviso: voce esta usando a chave padrao. Troque com --key ou CHAT_SHARED_KEY.")

        while True:
            conn, addr = server_sock.accept()
            thread = threading.Thread(target=handle_client, args=(conn, addr, shared_secret), daemon=True)
            thread.start()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Servidor de chat TCP com salas e criptografia didatica")
    parser.add_argument("--host", default="0.0.0.0", help="Endereco para bind (padrao: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=5000, help="Porta TCP (padrao: 5000)")
    parser.add_argument(
        "--key",
        default=os.getenv("CHAT_SHARED_KEY", "troque-esta-chave"),
        help="Chave compartilhada para criptografia",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_server(args.host, args.port, args.key)
