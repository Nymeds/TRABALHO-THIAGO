import argparse
import os
import queue
import socket
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from crypto_utils import decrypt_text, encrypt_text
from protocol import recv_packet, send_packet


class ChatGUI(tk.Tk):
    def __init__(self, host: str, port: int, shared_secret: str) -> None:
        super().__init__()
        self.title("Chat Seguro - Cliente")
        self.geometry("960x640")
        self.minsize(820, 560)

        self.default_host = host
        self.default_port = port
        self.host = host
        self.port = port
        self.shared_secret = shared_secret

        self.sock: Optional[socket.socket] = None
        self.listener_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.send_lock = threading.Lock()
        self.event_queue: "queue.Queue[dict]" = queue.Queue()
        self.user_initiated_disconnect = False

        self.username = ""
        self.current_room: Optional[str] = None
        self.room_items: list[str] = []

        self.style = ttk.Style(self)
        if "clam" in self.style.theme_names():
            self.style.theme_use("clam")
        self._configure_styles()

        self._build_ui()
        self._show_screen(self.login_frame)
        self.after(120, self._poll_network_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_styles(self) -> None:
        self.configure(bg="#eef3fb")

        self.style.configure("App.TFrame", background="#eef3fb")
        self.style.configure("Card.TFrame", background="#ffffff")

        self.style.configure("Title.TLabel", background="#eef3fb", foreground="#10213f", font=("Segoe UI", 24, "bold"))
        self.style.configure("Section.TLabel", background="#eef3fb", foreground="#10213f", font=("Segoe UI", 20, "bold"))
        self.style.configure("CardTitle.TLabel", background="#ffffff", foreground="#142850", font=("Segoe UI", 16, "bold"))
        self.style.configure("Subtitle.TLabel", background="#eef3fb", foreground="#445677", font=("Segoe UI", 11))
        self.style.configure("CardSubtitle.TLabel", background="#ffffff", foreground="#50617f", font=("Segoe UI", 10))
        self.style.configure("Hint.TLabel", background="#eef3fb", foreground="#5e6f8d", font=("Segoe UI", 10))

        self.style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), padding=(12, 8))
        self.style.configure("Action.TButton", font=("Segoe UI", 10), padding=(10, 7))
        self.style.configure("Ghost.TButton", font=("Segoe UI", 10), padding=(10, 6))

        self.style.configure(
            "Status.TLabel",
            background="#d9e7ff",
            foreground="#13305f",
            font=("Segoe UI", 10),
            padding=(10, 8),
        )

        self.style.configure("Rooms.Treeview", rowheight=34, font=("Segoe UI", 10), background="#ffffff", fieldbackground="#ffffff")
        self.style.configure("Rooms.Treeview.Heading", font=("Segoe UI", 10, "bold"))

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=20, style="App.TFrame")
        root.pack(fill=tk.BOTH, expand=True)
        self.root_frame = root

        self.login_frame = ttk.Frame(root, style="App.TFrame")
        self._build_login(self.login_frame)

        self.lobby_frame = ttk.Frame(root, style="App.TFrame")
        self._build_lobby(self.lobby_frame)

        self.chat_frame = ttk.Frame(root, style="App.TFrame")
        self._build_chat(self.chat_frame)

        self.status_label = ttk.Label(root, text="Desconectado", style="Status.TLabel")
        self.status_label.pack(fill=tk.X, pady=(10, 0))

    def _build_login(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        ttk.Label(frame, text="Chat Seguro", style="Title.TLabel").grid(row=0, column=0, pady=(28, 8))

        card = ttk.Frame(frame, style="Card.TFrame", padding=(32, 26))
        card.grid(row=1, column=0, sticky="n", pady=(0, 10))
        card.columnconfigure(0, weight=1)

        ttk.Label(card, text="Entrar no Servidor", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(
            card,
            text="Use o identificador do servidor para se conectar pela rede local.",
            style="CardSubtitle.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 16))

        ttk.Label(card, text="Identificador do servidor (IP:porta):", style="CardSubtitle.TLabel").grid(
            row=2, column=0, columnspan=2, sticky="w"
        )
        self.server_id_entry = ttk.Entry(card, width=36, font=("Segoe UI", 11))
        self.server_id_entry.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 12))
        self.server_id_entry.insert(0, f"{self.default_host}:{self.default_port}")

        ttk.Label(card, text="Nome de usuario:", style="CardSubtitle.TLabel").grid(row=4, column=0, columnspan=2, sticky="w")
        self.login_name_entry = ttk.Entry(card, width=26, font=("Segoe UI", 11))
        self.login_name_entry.grid(row=5, column=0, sticky="ew", pady=(4, 0), padx=(0, 8))
        self.login_name_entry.bind("<Return>", lambda _: self._connect())

        self.connect_button = ttk.Button(card, text="Conectar", style="Primary.TButton", command=self._connect)
        self.connect_button.grid(row=5, column=1, sticky="ew")

        ttk.Label(frame, text="Exemplo: 192.168.0.15:5000", style="Hint.TLabel").grid(row=2, column=0, pady=(8, 0))

    def _build_lobby(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        header = ttk.Frame(frame, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(2, 12))
        header.columnconfigure(0, weight=1)

        self.lobby_title = ttk.Label(header, text="Salas", style="Section.TLabel")
        self.lobby_title.grid(row=0, column=0, sticky="w")

        self.header_create_room_button = ttk.Button(
            header,
            text="Nova Sala",
            style="Primary.TButton",
            command=self._open_create_room_dialog,
        )
        self.header_create_room_button.grid(row=0, column=1, padx=(0, 8), sticky="e")

        ttk.Button(header, text="Desconectar", style="Ghost.TButton", command=self._disconnect_to_login).grid(
            row=0, column=2, sticky="e"
        )

        self.lobby_card = ttk.Frame(frame, style="Card.TFrame", padding=(22, 20))
        self.lobby_card.grid(row=1, column=0, sticky="nsew")
        self.lobby_card.columnconfigure(0, weight=1)
        self.lobby_card.rowconfigure(2, weight=1)

        ttk.Label(self.lobby_card, text="Escolha uma sala", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            self.lobby_card,
            text="Entre em uma sala existente ou crie uma nova em um clique.",
            style="CardSubtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 12))

        self.empty_state_frame = ttk.Frame(self.lobby_card, style="Card.TFrame")
        self.empty_state_frame.columnconfigure(0, weight=1)
        ttk.Label(
            self.empty_state_frame,
            text="Nenhuma sala ativa no momento.",
            style="CardTitle.TLabel",
        ).grid(row=0, column=0, pady=(8, 4))
        ttk.Label(
            self.empty_state_frame,
            text="Clique abaixo para criar a primeira sala.",
            style="CardSubtitle.TLabel",
        ).grid(row=1, column=0, pady=(0, 12))
        ttk.Button(
            self.empty_state_frame,
            text="Criar Primeira Sala",
            style="Primary.TButton",
            command=self._open_create_room_dialog,
        ).grid(row=2, column=0)

        self.rooms_table_frame = ttk.Frame(self.lobby_card, style="Card.TFrame")
        self.rooms_table_frame.columnconfigure(0, weight=1)
        self.rooms_table_frame.rowconfigure(0, weight=1)

        self.rooms_tree = ttk.Treeview(
            self.rooms_table_frame,
            columns=("ordem", "sala", "usuarios"),
            show="headings",
            style="Rooms.Treeview",
            height=9,
        )
        self.rooms_tree.heading("ordem", text="#")
        self.rooms_tree.heading("sala", text="Sala")
        self.rooms_tree.heading("usuarios", text="Usuarios")
        self.rooms_tree.column("ordem", width=50, anchor="center", stretch=False)
        self.rooms_tree.column("sala", width=430, anchor="w")
        self.rooms_tree.column("usuarios", width=110, anchor="center", stretch=False)
        self.rooms_tree.grid(row=0, column=0, sticky="nsew")
        self.rooms_tree.bind("<Double-1>", lambda _: self._join_selected_room())

        tree_scroll = ttk.Scrollbar(self.rooms_table_frame, orient="vertical", command=self.rooms_tree.yview)
        tree_scroll.grid(row=0, column=1, sticky="ns")
        self.rooms_tree.configure(yscrollcommand=tree_scroll.set)

        self.lobby_actions = ttk.Frame(self.lobby_card, style="Card.TFrame")
        self.lobby_actions.grid_columnconfigure(0, weight=1)

        self.enter_room_button = ttk.Button(
            self.lobby_actions,
            text="Entrar na Sala Selecionada",
            style="Primary.TButton",
            command=self._join_selected_room,
        )
        self.enter_room_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.create_room_button = ttk.Button(
            self.lobby_actions,
            text="Criar Nova Sala",
            style="Action.TButton",
            command=self._open_create_room_dialog,
        )
        self.create_room_button.grid(row=0, column=1, padx=(0, 8))

        self.refresh_button = ttk.Button(
            self.lobby_actions,
            text="Atualizar",
            style="Action.TButton",
            command=self._request_room_list,
        )
        self.refresh_button.grid(row=0, column=2)

        self._render_lobby_state()

    def _build_chat(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        header = ttk.Frame(frame, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(2, 10))
        header.columnconfigure(0, weight=1)

        self.chat_title = ttk.Label(header, text="Sala", style="Section.TLabel")
        self.chat_title.grid(row=0, column=0, sticky="w")

        self.chat_subtitle = ttk.Label(header, text="", style="Subtitle.TLabel")
        self.chat_subtitle.grid(row=1, column=0, sticky="w", pady=(2, 0))

        ttk.Button(header, text="Voltar para Salas", style="Action.TButton", command=self._leave_room).grid(
            row=0, column=1, rowspan=2, sticky="e"
        )

        chat_card = ttk.Frame(frame, style="Card.TFrame", padding=(14, 14))
        chat_card.grid(row=1, column=0, sticky="nsew")
        chat_card.columnconfigure(0, weight=1)
        chat_card.rowconfigure(0, weight=1)

        text_frame = ttk.Frame(chat_card, style="Card.TFrame")
        text_frame.grid(row=0, column=0, sticky="nsew")
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)

        self.chat_log = tk.Text(
            text_frame,
            wrap="word",
            state=tk.DISABLED,
            font=("Consolas", 11),
            background="#f8fbff",
            foreground="#12233f",
            insertbackground="#12233f",
            relief=tk.FLAT,
            padx=10,
            pady=10,
        )
        self.chat_log.grid(row=0, column=0, sticky="nsew")

        chat_scroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.chat_log.yview)
        chat_scroll.grid(row=0, column=1, sticky="ns")
        self.chat_log.configure(yscrollcommand=chat_scroll.set)

        composer = ttk.Frame(chat_card, style="Card.TFrame")
        composer.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        composer.columnconfigure(0, weight=1)

        self.chat_input = ttk.Entry(composer, font=("Segoe UI", 11))
        self.chat_input.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.chat_input.bind("<Return>", lambda _: self._send_chat_message())

        ttk.Button(composer, text="Enviar", style="Primary.TButton", command=self._send_chat_message).grid(
            row=0, column=1
        )

    def _show_screen(self, frame: ttk.Frame) -> None:
        for child in (self.login_frame, self.lobby_frame, self.chat_frame):
            child.pack_forget()
        frame.pack(fill=tk.BOTH, expand=True)

    def _render_lobby_state(self) -> None:
        has_rooms = bool(self.room_items)

        if has_rooms:
            self.empty_state_frame.grid_remove()
            self.rooms_table_frame.grid(row=2, column=0, sticky="nsew")
            self.lobby_actions.grid(row=3, column=0, sticky="ew", pady=(12, 0))
            self.lobby_actions.grid_columnconfigure(0, weight=1)
        else:
            self.rooms_table_frame.grid_remove()
            self.lobby_actions.grid_remove()
            self.empty_state_frame.grid(row=2, column=0, pady=(24, 30), sticky="ew")

    def _connect(self) -> None:
        name = self.login_name_entry.get().strip()
        if not name:
            messagebox.showwarning("Nome obrigatorio", "Informe um nome de usuario.")
            return

        server_id = self.server_id_entry.get().strip()
        try:
            host, port = self._parse_server_identifier(server_id)
        except ValueError as exc:
            messagebox.showwarning("Servidor invalido", str(exc))
            return

        self.connect_button.configure(state=tk.DISABLED)
        sock: Optional[socket.socket] = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(6)
            sock.connect((host, port))
            send_packet(sock, {"type": "hello", "name": name})

            response = recv_packet(sock)
            if response is None:
                raise ConnectionError("Servidor encerrou durante o handshake.")
            if response.get("type") == "error":
                raise ConnectionError(str(response.get("text", "Erro do servidor.")))
            if response.get("type") != "hello_ack":
                raise ConnectionError("Resposta inesperada no handshake.")

            self.username = str(response.get("name", name))
            self.host = host
            self.port = port
            self.sock = sock
            self.sock.settimeout(None)
            self.stop_event.clear()
            self.user_initiated_disconnect = False
            self._clear_event_queue()

            self.listener_thread = threading.Thread(target=self._listen_loop, daemon=True)
            self.listener_thread.start()

            self.lobby_title.configure(text=f"Salas - usuario: {self.username}")
            self._set_status(f"Conectado em {self.host}:{self.port} como {self.username}")
            self._show_screen(self.lobby_frame)
            self._update_room_list(response.get("rooms", []))
            self._request_room_list()
        except Exception as exc:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
            messagebox.showerror("Falha de conexao", str(exc))
        finally:
            self.connect_button.configure(state=tk.NORMAL)

    def _parse_server_identifier(self, value: str) -> tuple[str, int]:
        text = value.strip()
        if not text:
            raise ValueError("Informe IP:porta do servidor.")

        host = text
        port = self.default_port
        if ":" in text:
            host_part, port_part = text.rsplit(":", 1)
            host = host_part.strip()
            try:
                port = int(port_part.strip())
            except ValueError as exc:
                raise ValueError("Porta invalida. Use um numero entre 1 e 65535.") from exc

        if not host:
            raise ValueError("IP/host do servidor nao pode ficar vazio.")
        if port < 1 or port > 65535:
            raise ValueError("Porta fora do intervalo permitido (1-65535).")

        return host, port

    def _listen_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                sock = self.sock
                if sock is None:
                    break
                packet = recv_packet(sock)
            except (ConnectionError, OSError, ValueError) as exc:
                if not self.stop_event.is_set():
                    self.event_queue.put({"type": "disconnected", "text": str(exc)})
                break

            if packet is None:
                if not self.stop_event.is_set():
                    self.event_queue.put({"type": "disconnected", "text": "Servidor desconectou."})
                break

            self.event_queue.put(packet)

        self.stop_event.set()

    def _poll_network_events(self) -> None:
        while True:
            try:
                packet = self.event_queue.get_nowait()
            except queue.Empty:
                break
            self._handle_packet(packet)

        self.after(120, self._poll_network_events)

    def _handle_packet(self, packet: dict) -> None:
        packet_type = packet.get("type")

        if packet_type == "room_list":
            self._update_room_list(packet.get("rooms", []))
            return

        if packet_type == "joined_room":
            room = str(packet.get("room", "")).strip()
            if room:
                self.current_room = room
                self.chat_title.configure(text=f"Sala: {room}")
                self.chat_subtitle.configure(text=f"Voce entrou como {self.username}")
                self._clear_chat_log()
                self._show_screen(self.chat_frame)
                self.chat_input.focus_set()
                self._set_status(f"Conectado | Sala atual: {room}")
            return

        if packet_type == "room_history":
            room = str(packet.get("room", "")).strip()
            messages = packet.get("messages", [])
            if room and self.current_room == room:
                self._render_room_history(messages)
            return

        if packet_type == "left_room":
            self.current_room = None
            self._show_screen(self.lobby_frame)
            self._request_room_list()
            self._set_status(f"Conectado em {self.host}:{self.port} como {self.username}")
            return

        if packet_type == "broadcast":
            room = str(packet.get("room", ""))
            sender = str(packet.get("from", "?"))
            payload = packet.get("payload")
            if not isinstance(payload, dict):
                return

            try:
                text = decrypt_text(payload, self.shared_secret)
            except ValueError:
                self._append_chat_line("[ERRO] Mensagem com autenticacao invalida.")
                return

            if self.current_room == room:
                self._append_chat_line(f"[{sender}] {text}")
            return

        if packet_type == "error":
            message = str(packet.get("text", "Erro desconhecido."))
            if self.current_room:
                self._append_chat_line(f"[ERRO] {message}")
            else:
                messagebox.showwarning("Aviso", message)
            return

        if packet_type == "disconnected":
            message = str(packet.get("text", "Conexao encerrada."))
            self._hard_disconnect()
            if not self.user_initiated_disconnect:
                if "10038" in message:
                    message = "Conexao encerrada."
                messagebox.showwarning("Desconectado", message)
            return

    def _render_room_history(self, messages: object) -> None:
        if not isinstance(messages, list):
            self._append_chat_line("[Historico] Nao foi possivel carregar mensagens anteriores.")
            return

        if not messages:
            self._append_chat_line("[Historico] Sala sem mensagens anteriores.")
            return

        self._append_chat_line("[Historico] Ultimas mensagens criptografadas carregadas:")
        for item in messages:
            if not isinstance(item, dict):
                continue
            sender = str(item.get("sender", "?"))
            payload = item.get("payload")
            if not isinstance(payload, dict):
                continue

            try:
                text = decrypt_text(payload, self.shared_secret)
            except ValueError:
                self._append_chat_line(f"[{sender}] [mensagem invalida no historico]")
                continue

            self._append_chat_line(f"[{sender}] {text}")

    def _update_room_list(self, rooms: object) -> None:
        for item in self.rooms_tree.get_children():
            self.rooms_tree.delete(item)
        self.room_items = []

        parsed_rooms: list[tuple[str, int]] = []
        if isinstance(rooms, list):
            for item in rooms:
                if not isinstance(item, dict):
                    continue
                room_name = str(item.get("name", "")).strip()
                if not room_name:
                    continue

                try:
                    users = int(item.get("users", 0))
                except (TypeError, ValueError):
                    users = 0
                parsed_rooms.append((room_name, max(0, users)))

        parsed_rooms.sort(key=lambda room: room[0].casefold())

        for idx, (room_name, users) in enumerate(parsed_rooms, start=1):
            iid = f"room_{idx}"
            self.rooms_tree.insert("", tk.END, iid=iid, values=(idx, room_name, users))
            self.room_items.append(room_name)

        if self.room_items:
            first_item = self.rooms_tree.get_children()[0]
            self.rooms_tree.selection_set(first_item)
            self.rooms_tree.focus(first_item)

        self._render_lobby_state()

    def _request_room_list(self) -> None:
        self._send({"type": "list_rooms"}, silent=True)

    def _open_create_room_dialog(self) -> None:
        if self.sock is None:
            messagebox.showerror("Sem conexao", "Conecte-se ao servidor primeiro.")
            return

        dialog = tk.Toplevel(self)
        dialog.title("Criar Nova Sala")
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)
        dialog.configure(bg="#eef3fb")

        body = ttk.Frame(dialog, padding=(18, 16), style="App.TFrame")
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)

        ttk.Label(body, text="Nome da Nova Sala", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(body, text="Use um nome curto e facil de identificar.", style="Subtitle.TLabel").grid(
            row=1, column=0, sticky="w", pady=(2, 10)
        )

        room_entry = ttk.Entry(body, width=34, font=("Segoe UI", 11))
        room_entry.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        room_entry.focus_set()

        error_label = ttk.Label(body, text="", style="Hint.TLabel")
        error_label.grid(row=3, column=0, sticky="w", pady=(0, 8))

        actions = ttk.Frame(body, style="App.TFrame")
        actions.grid(row=4, column=0, sticky="e")

        def submit() -> None:
            room_name = room_entry.get().strip()
            if not room_name:
                error_label.configure(text="Informe um nome de sala valido.")
                return
            self._send({"type": "create_room", "room": room_name})
            dialog.destroy()

        ttk.Button(actions, text="Cancelar", style="Ghost.TButton", command=dialog.destroy).grid(
            row=0, column=0, padx=(0, 8)
        )
        ttk.Button(actions, text="Criar Sala", style="Primary.TButton", command=submit).grid(row=0, column=1)

        room_entry.bind("<Return>", lambda _: submit())
        dialog.bind("<Escape>", lambda _: dialog.destroy())

        dialog.update_idletasks()
        w, h = dialog.winfo_width(), dialog.winfo_height()
        x = self.winfo_rootx() + (self.winfo_width() // 2) - (w // 2)
        y = self.winfo_rooty() + (self.winfo_height() // 2) - (h // 2)
        dialog.geometry(f"{w}x{h}+{x}+{y}")

    def _join_selected_room(self) -> None:
        if not self.room_items:
            messagebox.showinfo("Sem salas", "Nenhuma sala aberta para entrar.")
            return

        selection = self.rooms_tree.selection()
        if not selection:
            messagebox.showinfo("Selecao", "Selecione uma sala na lista.")
            return

        values = self.rooms_tree.item(selection[0], "values")
        if len(values) < 2:
            return

        room_name = str(values[1]).strip()
        if room_name:
            self._send({"type": "join_room", "room": room_name})

    def _leave_room(self) -> None:
        self._send({"type": "leave_room"})

    def _send_chat_message(self) -> None:
        text = self.chat_input.get().strip()
        if not text:
            return

        packet = {
            "type": "message",
            "payload": encrypt_text(text, self.shared_secret),
        }
        if self._send(packet):
            self.chat_input.delete(0, tk.END)

    def _append_chat_line(self, text: str) -> None:
        self.chat_log.configure(state=tk.NORMAL)
        self.chat_log.insert(tk.END, f"{text}\n")
        self.chat_log.see(tk.END)
        self.chat_log.configure(state=tk.DISABLED)

    def _clear_chat_log(self) -> None:
        self.chat_log.configure(state=tk.NORMAL)
        self.chat_log.delete("1.0", tk.END)
        self.chat_log.configure(state=tk.DISABLED)

    def _send(self, packet: dict, silent: bool = False) -> bool:
        if self.sock is None:
            if not silent:
                messagebox.showerror("Sem conexao", "Conecte-se ao servidor primeiro.")
            return False

        try:
            with self.send_lock:
                if self.sock is None:
                    return False
                send_packet(self.sock, packet)
            return True
        except OSError:
            if not self.user_initiated_disconnect:
                self.event_queue.put({"type": "disconnected", "text": "Falha ao enviar pacote."})
            return False

    def _disconnect_to_login(self) -> None:
        self.user_initiated_disconnect = True
        self._hard_disconnect()
        self._show_screen(self.login_frame)
        self._set_status("Desconectado")

    def _hard_disconnect(self) -> None:
        self.stop_event.set()

        sock = self.sock
        self.sock = None
        self.current_room = None
        self.room_items = []

        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

        self._clear_chat_log()
        self._update_room_list([])

    def _clear_event_queue(self) -> None:
        while True:
            try:
                self.event_queue.get_nowait()
            except queue.Empty:
                break

    def _on_close(self) -> None:
        self.user_initiated_disconnect = True
        self._hard_disconnect()
        self.destroy()

    def _set_status(self, text: str) -> None:
        self.status_label.configure(text=text)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cliente GUI de chat TCP com salas e criptografia")
    parser.add_argument("--host", default="127.0.0.1", help="Endereco do servidor (padrao: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="Porta TCP do servidor (padrao: 5000)")
    parser.add_argument(
        "--key",
        default=os.getenv("CHAT_SHARED_KEY", "troque-esta-chave"),
        help="Chave compartilhada para criptografia",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    app = ChatGUI(args.host, args.port, args.key)
    app.mainloop()


if __name__ == "__main__":
    main()
