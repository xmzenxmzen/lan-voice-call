"""Peer discovery over UDP broadcast + multicast.

Each peer announces itself every `PRESENCE_INTERVAL` seconds via both:
  - UDP broadcast on 255.255.255.255:50000
  - UDP multicast on 224.0.0.1:50001

Announcements are small JSON packets:
    {"id": "<uuid>", "username": "<name>", "ip": "<ip>", "port": 50002,
     "audio_port": 50010, "ts": <epoch>}

The class maintains an in-memory dict of currently-online peers and emits
Qt signals when peers appear, change, or disappear.
"""
from __future__ import annotations

import json
import socket
import struct
import threading
import time
import uuid
from typing import Dict, Optional

from PyQt5.QtCore import QObject, pyqtSignal

from .. import config


class Peer:
    """Snapshot of a discovered peer."""
    __slots__ = ("id", "username", "ip", "port", "audio_port", "last_seen")

    def __init__(self, id: str, username: str, ip: str, port: int, audio_port: int):
        self.id = id
        self.username = username
        self.ip = ip
        self.port = port
        self.audio_port = audio_port
        self.last_seen = time.time()

    def touch(self) -> None:
        self.last_seen = time.time()

    def __repr__(self) -> str:
        return f"Peer({self.username}@{self.ip})"


class Discovery(QObject):
    """Announces presence on the LAN and tracks discovered peers.

    Signals:
        peer_joined  (str id, str username, str ip, int port, int audio_port)
        peer_updated (str id, str username, str ip, int port, int audio_port)
        peer_left    (str id, str username)
    """

    peer_joined = pyqtSignal(str, str, str, int, int)
    peer_updated = pyqtSignal(str, str, str, int, int)
    peer_left = pyqtSignal(str, str)

    def __init__(self, username: str, user_id: Optional[str] = None):
        super().__init__()
        self.username = username
        self.user_id = user_id or config.machine_id()
        self.local_ip = config.get_local_ip()
        self._peers: Dict[str, Peer] = {}
        self._lock = threading.RLock()
        self._running = threading.Event()
        self._threads: list[threading.Thread] = []

    # ---------- lifecycle ----------
    def start(self) -> None:
        if self._running.is_set():
            return
        self._running.set()
        # Listeners first so we don't miss early beacons
        for target in ("_listen_broadcast", "_listen_multicast"):
            t = threading.Thread(target=getattr(self, target), daemon=True, name=target)
            t.start()
            self._threads.append(t)
        for target in ("_beacon_loop", "_cleanup_loop"):
            t = threading.Thread(target=getattr(self, target), daemon=True, name=target)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        if not self._running.is_set():
            return
        self._send_goodbye()
        self._running.clear()
        # Threads are daemon; they'll exit on their own.

    def set_username(self, username: str) -> None:
        with self._lock:
            self.username = username

    # ---------- public API ----------
    def peers(self) -> Dict[str, Peer]:
        with self._lock:
            return dict(self._peers)

    def get_peer(self, peer_id: str) -> Optional[Peer]:
        with self._lock:
            return self._peers.get(peer_id)

    # ---------- internals ----------
    def _beacon_packet(self, goodbye: bool = False) -> bytes:
        payload = {
            "id": self.user_id,
            "username": self.username,
            "ip": self.local_ip,
            "port": config.SIGNALING_PORT,
            "audio_port": config.AUDIO_PORT,
            "ts": time.time(),
            "goodbye": goodbye,
        }
        return json.dumps(payload).encode("utf-8")

    def _beacon_loop(self) -> None:
        # Send a beacon immediately so peers appear fast.
        self._send_beacon()
        while self._running.is_set():
            try:
                self._send_beacon()
            except Exception:
                pass
            self._running.wait(config.PRESENCE_INTERVAL)

    def _send_beacon(self) -> None:
        pkt = self._beacon_packet()
        # Broadcast
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.sendto(pkt, ("<broadcast>", config.DISCOVERY_BROADCAST_PORT))
            s.close()
        except Exception:
            pass
        # Multicast
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 4)
            s.sendto(pkt, (config.DISCOVERY_MULTICAST_GROUP, config.DISCOVERY_MULTICAST_PORT))
            s.close()
        except Exception:
            pass

    def _send_goodbye(self) -> None:
        pkt = self._beacon_packet(goodbye=True)
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.sendto(pkt, ("<broadcast>", config.DISCOVERY_BROADCAST_PORT))
            s.close()
        except Exception:
            pass

    def _listen_broadcast(self) -> None:
        self._listen_udp(
            bind_addr=("0.0.0.0", config.DISCOVERY_BROADCAST_PORT),
            allow_broadcast=True,
        )

    def _listen_multicast(self) -> None:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                # SO_REUSEPORT avoids "address in use" when multiple instances run
                # on the same machine (Linux only; ignored on Windows).
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except (AttributeError, OSError):
                pass
            s.bind(("0.0.0.0", config.DISCOVERY_MULTICAST_PORT))
            mreq = struct.pack(
                "4sl",
                socket.inet_aton(config.DISCOVERY_MULTICAST_GROUP),
                socket.INADDR_ANY,
            )
            s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            self._recv_loop(s)
        except Exception:
            # Multicast may be blocked; broadcast still works.
            return

    def _listen_udp(self, bind_addr: tuple, allow_broadcast: bool) -> None:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except (AttributeError, OSError):
                pass
            if allow_broadcast:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.bind(bind_addr)
            self._recv_loop(s)
        except Exception:
            return

    def _recv_loop(self, s: socket.socket) -> None:
        s.settimeout(1.0)
        while self._running.is_set():
            try:
                data, _ = s.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                msg = json.loads(data.decode("utf-8", errors="replace"))
            except Exception:
                continue
            self._handle_presence(msg)

    def _handle_presence(self, msg: dict) -> None:
        peer_id = msg.get("id")
        if not peer_id or peer_id == self.user_id:
            return
        username = str(msg.get("username", "Unknown"))[:32]
        ip = str(msg.get("ip", ""))[:64]
        port = int(msg.get("port", config.SIGNALING_PORT))
        audio_port = int(msg.get("audio_port", config.AUDIO_PORT))

        # Ignore messages that lack a usable IP.
        if not ip:
            return

        # Goodbye -> remove
        if msg.get("goodbye"):
            with self._lock:
                peer = self._peers.pop(peer_id, None)
            if peer:
                self.peer_left.emit(peer.id, peer.username)
            return

        with self._lock:
            existing = self._peers.get(peer_id)
            if existing is None:
                self._peers[peer_id] = Peer(peer_id, username, ip, port, audio_port)
                is_new = True
                changed = False
            else:
                is_new = False
                changed = (
                    existing.username != username
                    or existing.ip != ip
                    or existing.port != port
                    or existing.audio_port != audio_port
                )
                existing.username = username
                existing.ip = ip
                existing.port = port
                existing.audio_port = audio_port
                existing.touch()

        if is_new:
            self.peer_joined.emit(peer_id, username, ip, port, audio_port)
        elif changed:
            self.peer_updated.emit(peer_id, username, ip, port, audio_port)

    def _cleanup_loop(self) -> None:
        while self._running.is_set():
            self._running.wait(config.CLEANUP_INTERVAL)
            now = time.time()
            expired: list[Peer] = []
            with self._lock:
                for pid, peer in list(self._peers.items()):
                    if now - peer.last_seen > config.USER_TIMEOUT:
                        expired.append(self._peers.pop(pid))
            for peer in expired:
                self.peer_left.emit(peer.id, peer.username)
