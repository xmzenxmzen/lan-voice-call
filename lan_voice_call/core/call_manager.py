"""Call manager: orchestrates 1-to-1 calls and multi-party conference mesh.

State machine
-------------
* IDLE          -> no active call
* CALLING       -> outbound call request sent, awaiting accept
* INCOMING      -> inbound call request received, awaiting user decision
* IN_CALL       -> audio flowing with one or more peers

For 1-to-1 calls:
    Alice presses Call -> call_request -> Bob's UI shows incoming.
    Bob accepts        -> call_accept (incl. audio_port) -> Alice opens audio.
    Either hangs up    -> call_end.

For conference mesh:
    Starter presses "Start Room" -> starts audio immediately, waits for invites.
    Others press "Join Room" on a discovered room host -> invite_room to host.
    Host responds with invite_room_ack listing current members; new peer then
    opens audio to each member (and announces itself).

To keep things robust we use a single 'members' dict keyed by peer_id.
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Dict, List, Optional, Tuple

from PyQt5.QtCore import QObject, pyqtSignal

from .. import config
from .audio_engine import AudioEngine
from . import signaling


class CallManager(QObject):
    """Coordinates discovery, signaling and the audio engine.

    Signals (all emitted on the Qt main thread via Qt's signal system):
        state_changed(str state)              - "idle"|"calling"|"incoming"|"in_call"
        incoming_call(str call_id, str name, str ip, bool conference)
        call_accepted(str call_id)
        call_rejected(str call_id, str reason)
        call_ended(str reason)
        peer_joined_call(str name, str ip)
        peer_left_call(str name, str ip)
        members_changed(list)                 - list of (peer_id, name, ip)
        audio_started()
        audio_stopped()
        info(str)                             - user-facing info
        error(str)                            - user-facing error
    """

    state_changed = pyqtSignal(str)
    incoming_call = pyqtSignal(str, str, str, bool)
    call_accepted = pyqtSignal(str)
    call_rejected = pyqtSignal(str, str)
    call_ended = pyqtSignal(str)
    peer_joined_call = pyqtSignal(str, str)
    peer_left_call = pyqtSignal(str, str)
    members_changed = pyqtSignal(list)
    audio_started = pyqtSignal()
    audio_stopped = pyqtSignal()
    info = pyqtSignal(str)
    error = pyqtSignal(str)

    STATE_IDLE = "idle"
    STATE_CALLING = "calling"
    STATE_INCOMING = "incoming"
    STATE_IN_CALL = "in_call"

    def __init__(self, username: str):
        super().__init__()
        self.username = username
        self.user_id = config.machine_id()
        self.local_ip = config.get_local_ip()

        # Networking
        from .discovery import Discovery
        self.discovery = Discovery(username, self.user_id)
        self.signaling_server = signaling.SignalingServer()

        # Audio
        self.audio = AudioEngine()

        # Active call state
        self._lock = threading.RLock()
        self._state = self.STATE_IDLE
        self._call_id: Optional[str] = None
        # peer_id -> {"name", "ip", "port", "audio_port"}
        self._members: Dict[str, dict] = {}
        # Track pending outbound call info for timeout
        self._outbound_call_started_at = 0.0
        # Conference host (when we joined someone else's room)
        self._conference_host: Optional[str] = None
        # Is this call a conference?
        self._is_conference = False
        # Incoming call buffer (so UI can match accept/reject)
        self._incoming: Dict[str, dict] = {}  # call_id -> {peer_id, name, ip, ...}

        # Timer for call timeout
        self._timeout_thread: Optional[threading.Thread] = None
        self._running = threading.Event()

        # Wire signaling
        self.signaling_server.message_received.connect(self._on_signaling)

        # Wire discovery to refresh member list
        self.discovery.peer_left.connect(self._on_peer_left_discovery)

    # -------------------------------------------------------- lifecycle
    def start(self) -> bool:
        """Start networking + presence. Audio starts on call connect."""
        ok_sig = self.signaling_server.start()
        if not ok_sig:
            self.error.emit(
                f"Cannot bind signaling port {config.SIGNALING_PORT}. "
                "Is another instance running?"
            )
            return False
        self.discovery.start()
        self._running.set()
        # Timeout watcher
        self._timeout_thread = threading.Thread(target=self._timeout_loop, daemon=True)
        self._timeout_thread.start()
        return True

    def stop(self) -> None:
        self._running.clear()
        # End any active call
        self.hang_up(reason="shutdown")
        self.audio.stop()
        self.discovery.stop()
        self.signaling_server.stop()

    def set_username(self, name: str) -> None:
        self.username = name
        self.discovery.set_username(name)

    # -------------------------------------------------------- state helpers
    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def _set_state(self, new_state: str) -> None:
        with self._lock:
            old = self._state
            self._state = new_state
        if old != new_state:
            self.state_changed.emit(new_state)

    def members(self) -> List[Tuple[str, str, str]]:
        with self._lock:
            return [
                (pid, m["name"], m["ip"]) for pid, m in self._members.items()
            ]

    def is_in_call(self) -> bool:
        return self.state == self.STATE_IN_CALL

    def is_conference(self) -> bool:
        with self._lock:
            return self._is_conference

    # -------------------------------------------------------- outbound call
    def call_peer(self, peer_id: str) -> bool:
        """Initiate a 1-to-1 call to a discovered peer."""
        if self.state != self.STATE_IDLE:
            self.error.emit("Already in a call.")
            return False
        peer = self.discovery.get_peer(peer_id)
        if not peer:
            self.error.emit("User no longer online.")
            return False
        call_id = signaling.new_call_id()
        with self._lock:
            self._call_id = call_id
            self._outbound_call_started_at = time.time()
            self._is_conference = False
            self._conference_host = None
        msg = {
            "type": "call_request",
            "call_id": call_id,
            "from": self.user_id,
            "from_name": self.username,
            "ip": self.local_ip,
            "audio_port": config.AUDIO_PORT,
            "conference": False,
        }
        ok = signaling.send_message(peer.ip, peer.port, msg)
        if not ok:
            self.error.emit(f"Cannot reach {peer.username}.")
            with self._lock:
                self._call_id = None
            return False
        self._set_state(self.STATE_CALLING)
        self.info.emit(f"Calling {peer.username}...")
        return True

    def start_conference(self) -> bool:
        """Start a new conference room. Other users will see and can join it."""
        if self.state != self.STATE_IDLE:
            self.error.emit("Already in a call.")
            return False
        call_id = signaling.new_call_id()
        with self._lock:
            self._call_id = call_id
            self._is_conference = True
            self._conference_host = None  # We are the host
        # Start audio immediately (no peers yet, but stream is ready).
        if not self.audio.start():
            with self._lock:
                self._call_id = None
                self._is_conference = False
            return False
        self._set_state(self.STATE_IN_CALL)
        self.audio_started.emit()
        self.info.emit("Conference room started. Invite others to join.")
        return True

    def join_conference(self, host_peer_id: str) -> bool:
        """Send an invite_room request to a discovered host."""
        if self.state != self.STATE_IDLE:
            self.error.emit("Already in a call.")
            return False
        peer = self.discovery.get_peer(host_peer_id)
        if not peer:
            self.error.emit("Host no longer online.")
            return False
        call_id = signaling.new_call_id()
        with self._lock:
            self._call_id = call_id
            self._is_conference = True
            self._conference_host = host_peer_id
            self._outbound_call_started_at = time.time()
        msg = {
            "type": "join_room",
            "call_id": call_id,
            "from": self.user_id,
            "from_name": self.username,
            "ip": self.local_ip,
            "audio_port": config.AUDIO_PORT,
        }
        ok = signaling.send_message(peer.ip, peer.port, msg)
        if not ok:
            self.error.emit(f"Cannot reach host {peer.username}.")
            with self._lock:
                self._call_id = None
                self._is_conference = False
                self._conference_host = None
            return False
        self._set_state(self.STATE_CALLING)
        self.info.emit(f"Joining {peer.username}'s room...")
        return True

    # -------------------------------------------------------- inbound call
    def accept_incoming(self, call_id: str) -> bool:
        """User clicked Accept on an incoming call."""
        with self._lock:
            info = self._incoming.pop(call_id, None)
        if not info:
            self.error.emit("This call is no longer available.")
            return False
        # Open audio
        if not self.audio.start():
            self._set_state(self.STATE_IDLE)
            return False
        # Register the caller as a peer
        self.audio.add_peer(info["peer_id"], info["ip"], info["audio_port"])
        with self._lock:
            self._call_id = call_id
            self._is_conference = bool(info.get("conference", False))
            self._members[info["peer_id"]] = {
                "name": info["name"],
                "ip": info["ip"],
                "port": info["port"],
                "audio_port": info["audio_port"],
            }
        # Send accept with our audio port
        msg = {
            "type": "call_accept",
            "call_id": call_id,
            "from": self.user_id,
            "from_name": self.username,
            "ip": self.local_ip,
            "audio_port": config.AUDIO_PORT,
            "conference": bool(info.get("conference", False)),
        }
        signaling.send_message(info["ip"], info["port"], msg)
        self._set_state(self.STATE_IN_CALL)
        self.audio_started.emit()
        self.members_changed.emit(self.members())
        return True

    def reject_incoming(self, call_id: str, reason: str = "declined") -> None:
        with self._lock:
            info = self._incoming.pop(call_id, None)
        if not info:
            return
        msg = {
            "type": "call_reject",
            "call_id": call_id,
            "from": self.user_id,
            "reason": reason,
        }
        signaling.send_message(info["ip"], info["port"], msg)

    # -------------------------------------------------------- hangup
    def hang_up(self, reason: str = "user_hangup") -> None:
        """End the current call/room and notify peers."""
        with self._lock:
            call_id = self._call_id
            members = dict(self._members)
            self._call_id = None
            self._members.clear()
            self._is_conference = False
            self._conference_host = None
        if not call_id:
            self._set_state(self.STATE_IDLE)
            return
        # Notify every peer
        msg = {
            "type": "call_end",
            "call_id": call_id,
            "from": self.user_id,
            "reason": reason,
        }
        for m in members.values():
            signaling.send_message(m["ip"], m["port"], msg)
        # Stop audio
        self.audio.stop()
        self.audio_stopped.emit()
        self._set_state(self.STATE_IDLE)
        self.call_ended.emit(reason)
        self.members_changed.emit([])

    # -------------------------------------------------------- signaling
    def _on_signaling(self, remote_ip: str, msg: dict) -> None:
        t = msg.get("type")
        if t == "call_request":
            self._handle_call_request(msg, remote_ip)
        elif t == "call_accept":
            self._handle_call_accept(msg, remote_ip)
        elif t == "call_reject":
            self._handle_call_reject(msg)
        elif t == "call_end":
            self._handle_call_end(msg)
        elif t == "join_room":
            self._handle_join_room(msg, remote_ip)
        elif t == "room_members":
            self._handle_room_members(msg, remote_ip)
        elif t == "room_new_peer":
            self._handle_room_new_peer(msg, remote_ip)

    def _handle_call_request(self, msg: dict, remote_ip: str) -> None:
        # Drop if we're busy
        if self.state != self.STATE_IDLE:
            signaling.send_message(
                remote_ip,
                int(msg.get("port", config.SIGNALING_PORT)),
                {
                    "type": "call_reject",
                    "call_id": msg.get("call_id"),
                    "from": self.user_id,
                    "reason": "busy",
                },
            )
            return
        call_id = msg.get("call_id")
        if not call_id:
            return
        with self._lock:
            self._incoming[call_id] = {
                "peer_id": msg.get("from"),
                "name": msg.get("from_name", "Unknown"),
                "ip": remote_ip,
                "port": int(msg.get("port", config.SIGNALING_PORT)),
                "audio_port": int(msg.get("audio_port", config.AUDIO_PORT)),
                "conference": bool(msg.get("conference", False)),
            }
        self._set_state(self.STATE_INCOMING)
        self.incoming_call.emit(
            call_id,
            msg.get("from_name", "Unknown"),
            remote_ip,
            bool(msg.get("conference", False)),
        )

    def _handle_call_accept(self, msg: dict, remote_ip: str) -> None:
        with self._lock:
            call_id = self._call_id
        if not call_id or call_id != msg.get("call_id"):
            return  # Stale accept for a different call.
        if self.state != self.STATE_CALLING:
            return
        # Open audio
        if not self.audio.start():
            self.hang_up(reason="audio_init_failed")
            return
        peer_id = msg.get("from")
        audio_port = int(msg.get("audio_port", config.AUDIO_PORT))
        self.audio.add_peer(peer_id, remote_ip, audio_port)
        with self._lock:
            self._members[peer_id] = {
                "name": msg.get("from_name", "Unknown"),
                "ip": remote_ip,
                "port": int(msg.get("port", config.SIGNALING_PORT)),
                "audio_port": audio_port,
            }
        self._set_state(self.STATE_IN_CALL)
        self.audio_started.emit()
        self.members_changed.emit(self.members())

    def _handle_call_reject(self, msg: dict) -> None:
        with self._lock:
            call_id = self._call_id
        if not call_id or call_id != msg.get("call_id"):
            return
        if self.state != self.STATE_CALLING:
            return
        reason = msg.get("reason", "declined")
        with self._lock:
            self._call_id = None
        self._set_state(self.STATE_IDLE)
        self.call_rejected.emit(call_id, reason)

    def _handle_call_end(self, msg: dict) -> None:
        with self._lock:
            call_id = self._call_id
        if not call_id or call_id != msg.get("call_id"):
            return
        peer_id = msg.get("from")
        # If in a conference with multiple peers, just remove this peer.
        with self._lock:
            if self._is_conference and len(self._members) > 1:
                removed = self._members.pop(peer_id, None)
                self.audio.remove_peer(peer_id)
                if removed:
                    self.peer_left_call.emit(removed["name"], removed["ip"])
                self.members_changed.emit(self.members())
                return
        # 1-to-1 call (or last conference peer): end the whole call.
        self.audio.stop()
        with self._lock:
            self._call_id = None
            self._members.clear()
            self._is_conference = False
            self._conference_host = None
        self.audio_stopped.emit()
        self._set_state(self.STATE_IDLE)
        self.call_ended.emit(msg.get("reason", "remote_hangup"))
        self.members_changed.emit([])

    # ---------------------------------------------------- conference mesh
    def _handle_join_room(self, msg: dict, remote_ip: str) -> None:
        """Someone wants to join our conference room."""
        if self.state != self.STATE_IN_CALL or not self._is_conference:
            # Not a host (or not in a call) -> reject politely.
            signaling.send_message(
                remote_ip,
                int(msg.get("port", config.SIGNALING_PORT)),
                {
                    "type": "call_reject",
                    "call_id": msg.get("call_id"),
                    "from": self.user_id,
                    "reason": "no_room",
                },
            )
            return
        new_peer_id = msg.get("from")
        new_peer_name = msg.get("from_name", "Unknown")
        new_peer_audio_port = int(msg.get("audio_port", config.AUDIO_PORT))
        new_peer_port = int(msg.get("port", config.SIGNALING_PORT))

        # Check capacity
        with self._lock:
            if len(self._members) >= config.CONFERENCE_MAX_PEERS:
                signaling.send_message(
                    remote_ip,
                    new_peer_port,
                    {
                        "type": "call_reject",
                        "call_id": msg.get("call_id"),
                        "from": self.user_id,
                        "reason": "room_full",
                    },
                )
                return

        # Register the new peer in audio engine.
        self.audio.add_peer(new_peer_id, remote_ip, new_peer_audio_port)

        with self._lock:
            self._members[new_peer_id] = {
                "name": new_peer_name,
                "ip": remote_ip,
                "port": new_peer_port,
                "audio_port": new_peer_audio_port,
            }
            members_snapshot = [
                (pid, m["name"], m["ip"], m["audio_port"])
                for pid, m in self._members.items()
                if pid != new_peer_id
            ]
            # Also include ourselves so the new peer connects back to us.
            members_snapshot.append(
                (self.user_id, self.username, self.local_ip, config.AUDIO_PORT)
            )

        # Reply with the list of existing members (including us).
        msg_reply = {
            "type": "room_members",
            "call_id": msg.get("call_id"),
            "from": self.user_id,
            "from_name": self.username,
            "ip": self.local_ip,
            "audio_port": config.AUDIO_PORT,
            "members": members_snapshot,
        }
        signaling.send_message(remote_ip, new_peer_port, msg_reply)

        # Notify existing members about the new peer so they also connect.
        notify = {
            "type": "room_new_peer",
            "call_id": self._call_id,
            "from": self.user_id,
            "peer_id": new_peer_id,
            "peer_name": new_peer_name,
            "peer_ip": remote_ip,
            "peer_audio_port": new_peer_audio_port,
        }
        with self._lock:
            existing = [
                (m["ip"], m["port"]) for pid, m in self._members.items()
                if pid != new_peer_id
            ]
        for ip, port in existing:
            signaling.send_message(ip, port, notify)

        self.peer_joined_call.emit(new_peer_name, remote_ip)
        self.members_changed.emit(self.members())

    def _handle_room_members(self, msg: dict, remote_ip: str) -> None:
        """Host replied with the list of members in the room we're joining."""
        if self.state != self.STATE_CALLING:
            return
        # Open audio
        if not self.audio.start():
            self._set_state(self.STATE_IDLE)
            return
        # Add host as first peer
        host_id = msg.get("from")
        host_audio_port = int(msg.get("audio_port", config.AUDIO_PORT))
        self.audio.add_peer(host_id, remote_ip, host_audio_port)
        with self._lock:
            self._members[host_id] = {
                "name": msg.get("from_name", "Host"),
                "ip": remote_ip,
                "port": config.SIGNALING_PORT,
                "audio_port": host_audio_port,
            }
            # Then every other listed member.
            for entry in msg.get("members", []):
                try:
                    pid, name, ip, aport = entry
                except (ValueError, TypeError):
                    continue
                if pid == self.user_id:
                    continue
                if pid == host_id:
                    continue  # Already added.
                self._members[pid] = {
                    "name": str(name),
                    "ip": str(ip),
                    "port": config.SIGNALING_PORT,
                    "audio_port": int(aport),
                }
                self.audio.add_peer(pid, str(ip), int(aport))
        # Tell each existing member (except host, who already knows) to add us.
        # The host already notified them via room_new_peer; this is a safety net
        # in case the host's notification raced our join.
        with self._lock:
            announce_targets = [
                (m["ip"], m["port"]) for pid, m in self._members.items()
                if pid != host_id
            ]
        announce = {
            "type": "room_new_peer",
            "call_id": self._call_id,
            "from": self.user_id,
            "peer_id": self.user_id,
            "peer_name": self.username,
            "peer_ip": self.local_ip,
            "peer_audio_port": config.AUDIO_PORT,
        }
        for ip, port in announce_targets:
            signaling.send_message(ip, port, announce)

        self._set_state(self.STATE_IN_CALL)
        self.audio_started.emit()
        self.members_changed.emit(self.members())

    def _handle_room_new_peer(self, msg: dict, remote_ip: str) -> None:
        """A new peer has joined the conference. Add them to our audio engine."""
        if self.state != self.STATE_IN_CALL:
            return
        peer_id = msg.get("peer_id")
        peer_name = msg.get("peer_name", "Unknown")
        peer_ip = msg.get("peer_ip", remote_ip)
        peer_audio_port = int(msg.get("peer_audio_port", config.AUDIO_PORT))
        if not peer_id or peer_id == self.user_id:
            return
        with self._lock:
            if peer_id in self._members:
                return  # Already know about them.
        self.audio.add_peer(peer_id, peer_ip, peer_audio_port)
        with self._lock:
            self._members[peer_id] = {
                "name": peer_name,
                "ip": peer_ip,
                "port": config.SIGNALING_PORT,
                "audio_port": peer_audio_port,
            }
        self.peer_joined_call.emit(peer_name, peer_ip)
        self.members_changed.emit(self.members())

    # ---------------------------------------------------- peer left LAN
    def _on_peer_left_discovery(self, peer_id: str, name: str) -> None:
        """A peer disappeared from discovery. If they're in our call, drop them."""
        with self._lock:
            member = self._members.get(peer_id)
            if not member:
                return
            self._members.pop(peer_id, None)
            remaining = len(self._members)
        self.audio.remove_peer(peer_id)
        self.peer_left_call.emit(name, member["ip"])
        self.members_changed.emit(self.members())
        # If that was the last peer (and we were in 1-to-1), end the call.
        if remaining == 0:
            self.hang_up(reason="peer_offline")

    # ---------------------------------------------------- timeout watcher
    def _timeout_loop(self) -> None:
        """Auto-cancel an unanswered outbound call after CALL_TIMEOUT seconds."""
        while self._running.is_set():
            self._running.wait(1.0)
            with self._lock:
                state = self._state
                started = self._outbound_call_started_at
            if state == self.STATE_CALLING and started:
                if time.time() - started > config.CALL_TIMEOUT:
                    self._outbound_call_started_at = 0.0
                    self._set_state(self.STATE_IDLE)
                    with self._lock:
                        self._call_id = None
                        self._conference_host = None
                        self._is_conference = False
                    self.call_rejected.emit("", "timeout")
