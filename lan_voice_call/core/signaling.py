"""TCP signaling channel for call setup, hangup, and conference invitations.

Each peer listens on TCP `SIGNALING_PORT` for incoming JSON messages (newline
delimited). The signaling layer is purely for *control*; the actual audio
travels over UDP directly between peers.

Message types:
    {"type": "call_request",  "call_id": str, "from": str, "from_name": str,
     "ip": str, "audio_port": int, "conference": bool}
    {"type": "call_accept",   "call_id": str, "audio_port": int}
    {"type": "call_reject",   "call_id": str, "reason": str}
    {"type": "call_end",      "call_id": str}
    {"type": "invite_room",   "call_id": str, "from": str, "from_name": str,
     "ip": str, "audio_port": int, "members": [[id, name, ip, audio_port], ...]}
    {"type": "ping"} / {"type": "pong"}
"""
from __future__ import annotations

import json
import socket
import threading
import uuid
from typing import Callable, Optional

from PyQt5.QtCore import QObject, pyqtSignal

from .. import config


class SignalingServer(QObject):
    """Listens for inbound TCP connections and dispatches JSON messages.

    Signals:
        message_received (str remote_ip, dict msg)
    """

    message_received = pyqtSignal(str, dict)

    def __init__(self):
        super().__init__()
        self._sock: Optional[socket.socket] = None
        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._conns_lock = threading.Lock()
        self._conns: list[socket.socket] = []

    def start(self) -> bool:
        if self._running.is_set():
            return True
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind(("0.0.0.0", config.SIGNALING_PORT))
            self._sock.listen(16)
            self._sock.settimeout(1.0)
        except OSError as e:
            self._sock = None
            return False
        self._running.set()
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._running.clear()
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        with self._conns_lock:
            for c in self._conns:
                try:
                    c.close()
                except OSError:
                    pass
            self._conns.clear()

    def _accept_loop(self) -> None:
        while self._running.is_set() and self._sock:
            try:
                conn, addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with self._conns_lock:
                self._conns.append(conn)
            t = threading.Thread(target=self._handle_conn, args=(conn, addr), daemon=True)
            t.start()

    def _handle_conn(self, conn: socket.socket, addr) -> None:
        conn.settimeout(1.0)
        buf = b""
        remote_ip = addr[0] if addr else ""
        try:
            while self._running.is_set():
                try:
                    chunk = conn.recv(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    try:
                        msg = json.loads(line.decode("utf-8", errors="replace"))
                    except Exception:
                        continue
                    if isinstance(msg, dict):
                        self.message_received.emit(remote_ip, msg)
        finally:
            try:
                conn.close()
            except OSError:
                pass
            with self._conns_lock:
                if conn in self._conns:
                    self._conns.remove(conn)


def send_message(ip: str, port: int, msg: dict, timeout: float = 2.0) -> bool:
    """Open a short-lived TCP connection to `ip:port` and send one JSON message.

    Returns True on success, False on any failure. Each message is sent on a
    fresh connection: keeps the protocol stateless and avoids stale sockets.
    """
    payload = (json.dumps(msg) + "\n").encode("utf-8")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((ip, port))
        s.sendall(payload)
        s.close()
        return True
    except OSError:
        try:
            s.close()
        except Exception:
            pass
        return False


def new_call_id() -> str:
    return uuid.uuid4().hex[:12]
