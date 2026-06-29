"""Main application window.

Layout
------
+--------------------------------------------------+
| Header bar: title | my username | status         |
+----------------+---------------------------------+
| Users on LAN   |  Call panel                     |
| (scroll list)  |  - current state                |
|                |  - members                      |
|                |  - controls (mute / volume)     |
|                |  - hang up / start room         |
+----------------+---------------------------------+
| Recent calls (compact)                           |
+--------------------------------------------------+
| Status bar: mic level | speaker level | LAN IP   |
+--------------------------------------------------+
"""
from __future__ import annotations

import time
from typing import Optional

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QSize
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QListWidget, QListWidgetItem, QSlider,
    QProgressBar, QStatusBar, QFrame, QScrollArea, QMessageBox,
)

from .. import config
from ..core import CallManager, CallLog
from ..core.discovery import Peer
from . import theme


# ---------------------------------------------------------------------------
# Custom widgets
# ---------------------------------------------------------------------------
class StatusDot(QLabel):
    """A small colored circle indicating call state."""

    _COLORS = {
        "idle": theme.TEXT_MUTED,
        "calling": theme.WARNING,
        "incoming": theme.WARNING,
        "in_call": theme.SUCCESS,
    }

    def __init__(self):
        super().__init__("●")
        self.set_state("idle")

    def set_state(self, state: str) -> None:
        color = self._COLORS.get(state, theme.TEXT_MUTED)
        self.setStyleSheet(f"color: {color}; font-size: 14px;")


class UserCardWidget(QWidget):
    """A single discovered-user row with Call / Join buttons."""

    call_clicked = pyqtSignal(str)   # peer_id
    join_clicked = pyqtSignal(str)   # peer_id (for conferences)

    def __init__(self, peer: Peer, parent=None):
        super().__init__(parent)
        self.peer_id = peer.id
        self._build(peer)

    def _build(self, peer: Peer) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        # Avatar circle with first letter
        avatar = QLabel(peer.username[0].upper() if peer.username else "?")
        avatar.setFixedSize(36, 36)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet(
            f"background-color: {theme.ACCENT}; color: white;"
            f"border-radius: 18px; font-weight: 700; font-size: 15px;"
        )

        info_box = QVBoxLayout()
        info_box.setSpacing(2)
        info_box.setContentsMargins(0, 0, 0, 0)
        self.name_label = QLabel(peer.username)
        self.name_label.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-weight: 600; font-size: 13px;"
        )
        self.ip_label = QLabel(peer.ip)
        self.ip_label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 11px;"
        )
        info_box.addWidget(self.name_label)
        info_box.addWidget(self.ip_label)

        # Buttons
        self.call_btn = QPushButton("Call")
        self.call_btn.setObjectName("primaryBtn")
        self.call_btn.setFixedWidth(72)
        self.call_btn.setCursor(Qt.PointingHandCursor)
        self.call_btn.clicked.connect(lambda: self.call_clicked.emit(self.peer_id))

        self.join_btn = QPushButton("Join Room")
        self.join_btn.setObjectName("ghostBtn")
        self.join_btn.setFixedWidth(92)
        self.join_btn.setCursor(Qt.PointingHandCursor)
        self.join_btn.setToolTip(
            "Join this user's conference room (only if they started one)."
        )
        self.join_btn.clicked.connect(lambda: self.join_clicked.emit(self.peer_id))

        layout.addWidget(avatar)
        layout.addLayout(info_box, stretch=1)
        layout.addWidget(self.call_btn)
        layout.addWidget(self.join_btn)

    def update_peer(self, peer: Peer) -> None:
        self.name_label.setText(peer.username)
        self.ip_label.setText(peer.ip)


class MemberBubble(QFrame):
    """A pill showing one in-call member."""

    def __init__(self, name: str, ip: str = "", is_self: bool = False):
        super().__init__()
        self.setObjectName("memberBubble")
        self.setStyleSheet(f"""
            QFrame#memberBubble {{
                background-color: {theme.BG_CARD};
                border: 1px solid {theme.BORDER_LIGHT};
                border-radius: 14px;
            }}
        """)
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 6, 10, 6)
        h.setSpacing(6)
        dot_color = theme.ACCENT if is_self else theme.SUCCESS
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {dot_color}; font-size: 10px;")
        name_lbl = QLabel(("You" if is_self else name) + (f"  ·  {ip}" if ip and not is_self else ""))
        name_lbl.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-size: 12px; font-weight: 500;"
        )
        h.addWidget(dot)
        h.addWidget(name_lbl)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    """Top-level application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("LAN Voice Call")
        self.resize(980, 660)
        self.setMinimumSize(820, 540)

        # State
        self.settings = config.load_settings()
        self.call_log = CallLog()
        self.manager = CallManager(self.settings["username"])
        self.manager.set_username(self.settings["username"])

        self._active_call_id: Optional[str] = None  # incoming call waiting on accept
        self._current_call_started_at: float = 0.0

        self._build_ui()
        self._connect_signals()

        # Auto-start networking
        if not self.manager.start():
            self._show_error(
                "Startup failed",
                "Could not bind the signaling port. Is another instance running?"
            )
        else:
            self.statusBar().showMessage(
                f"  Ready  ·  LAN IP: {self.manager.local_ip}  ·  Codec: {self.manager.audio.mode.upper()}",
                5000,
            )

        # Live duration timer
        self._duration_timer = QTimer(self)
        self._duration_timer.setInterval(1000)
        self._duration_timer.timeout.connect(self._update_duration)
        # Periodic refresh of user list (in case signals lag)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(2000)
        self._refresh_timer.timeout.connect(self._refresh_user_list)
        self._refresh_timer.start()

    # ---------------------------------------------------------- UI build
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        body_layout.addWidget(self._build_left_panel(), stretch=1)
        body_layout.addWidget(self._build_right_panel(), stretch=2)
        root.addWidget(body, stretch=1)

        root.addWidget(self._build_call_log_strip())
        self.setStatusBar(self._build_status_bar())

    def _build_header(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("headerBar")
        bar.setFixedHeight(56)
        h = QHBoxLayout(bar)
        h.setContentsMargins(18, 0, 18, 0)
        h.setSpacing(12)

        logo = QLabel("🎙")
        logo.setStyleSheet(f"font-size: 22px; color: {theme.ACCENT};")
        title = QLabel("LAN Voice Call")
        title.setObjectName("headerTitle")

        h.addWidget(logo)
        h.addWidget(title)
        h.addSpacing(20)

        h.addStretch(1)

        # Username editor
        user_label = QLabel("Display name:")
        user_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        self.username_edit = QLineEdit(self.settings["username"])
        self.username_edit.setMaxLength(24)
        self.username_edit.setFixedWidth(180)
        self.username_edit.editingFinished.connect(self._on_username_changed)

        h.addWidget(user_label)
        h.addWidget(self.username_edit)

        self.status_dot = StatusDot()
        self.status_label = QLabel("Idle")
        self.status_label.setObjectName("statusLabel")
        h.addSpacing(14)
        h.addWidget(self.status_dot)
        h.addWidget(self.status_label)
        return bar

    def _build_left_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("leftPanel")
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        head = QLabel("  USERS ON THIS LAN")
        head.setObjectName("sectionTitle")
        head.setContentsMargins(18, 18, 18, 8)
        v.addWidget(head)

        self.user_list = QListWidget()
        self.user_list.setSpacing(0)
        self.user_list.setUniformItemSizes(True)
        v.addWidget(self.user_list, stretch=1)

        # Empty hint
        self.empty_hint = QLabel("Looking for other devices…")
        self.empty_hint.setAlignment(Qt.AlignCenter)
        self.empty_hint.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 12px; padding: 30px;"
        )
        v.addWidget(self.empty_hint)
        self.empty_hint.setVisible(False)

        # Footer with start-room button
        foot = QFrame()
        foot.setStyleSheet(f"background-color: {theme.BG_PANEL};")
        foot_layout = QVBoxLayout(foot)
        foot_layout.setContentsMargins(14, 10, 14, 14)
        foot_layout.setSpacing(6)
        self.start_room_btn = QPushButton("Start Conference Room")
        self.start_room_btn.setObjectName("primaryBtn")
        self.start_room_btn.setCursor(Qt.PointingHandCursor)
        self.start_room_btn.setToolTip(
            "Start an empty conference room. Others can then click 'Join Room' on you."
        )
        self.start_room_btn.clicked.connect(self._on_start_room)
        foot_layout.addWidget(self.start_room_btn)
        v.addWidget(foot)
        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("rightPanel")
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(18)

        # State header
        self.state_title = QLabel("No active call")
        self.state_title.setObjectName("bigLabel")
        self.state_subtitle = QLabel("Pick a user on the left and press Call, "
                                      "or start a conference room.")
        self.state_subtitle.setObjectName("statusLabel")
        self.state_subtitle.setWordWrap(True)
        outer.addWidget(self.state_title)
        outer.addWidget(self.state_subtitle)

        # Duration label (visible only in call)
        self.duration_label = QLabel("")
        self.duration_label.setStyleSheet(
            f"color: {theme.ACCENT}; font-size: 14px; font-weight: 600;"
        )
        outer.addWidget(self.duration_label)
        self.duration_label.setVisible(False)

        # Members
        members_title = QLabel("PARTICIPANTS")
        members_title.setObjectName("sectionTitle")
        outer.addWidget(members_title)

        self.members_container = QWidget()
        self.members_layout = QVBoxLayout(self.members_container)
        self.members_layout.setContentsMargins(0, 0, 0, 0)
        self.members_layout.setSpacing(6)
        outer.addWidget(self.members_container)

        self.members_scroll = QScrollArea()
        self.members_scroll.setWidgetResizable(True)
        self.members_scroll.setWidget(self.members_container)
        outer.addWidget(self.members_scroll, stretch=1)

        # Audio controls bar
        ctrl = QFrame()
        ctrl.setStyleSheet(
            f"QFrame {{ background-color: {theme.BG_CARD}; border-radius: 10px; }}"
        )
        cl = QHBoxLayout(ctrl)
        cl.setContentsMargins(16, 12, 16, 12)
        cl.setSpacing(12)

        self.mute_btn = QPushButton("🎤  Mute")
        self.mute_btn.setObjectName("ghostBtn")
        self.mute_btn.setFixedWidth(110)
        self.mute_btn.setCursor(Qt.PointingHandCursor)
        self.mute_btn.setEnabled(False)
        self.mute_btn.clicked.connect(self._on_mute_toggle)

        vol_label = QLabel("🔊")
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(self.settings.get("volume", 80))
        self.volume_slider.setEnabled(False)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        self.vol_value_label = QLabel(f"{self.volume_slider.value()}%")
        self.vol_value_label.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: 11px; min-width: 30px;"
        )

        cl.addWidget(self.mute_btn)
        cl.addSpacing(8)
        cl.addWidget(vol_label)
        cl.addWidget(self.volume_slider, stretch=1)
        cl.addWidget(self.vol_value_label)
        outer.addWidget(ctrl)

        # Bottom buttons
        btns = QHBoxLayout()
        btns.setSpacing(10)
        self.hangup_btn = QPushButton("Hang Up")
        self.hangup_btn.setObjectName("dangerBtn")
        self.hangup_btn.setFixedHeight(42)
        self.hangup_btn.setCursor(Qt.PointingHandCursor)
        self.hangup_btn.setEnabled(False)
        self.hangup_btn.clicked.connect(self._on_hangup)
        btns.addStretch(1)
        btns.addWidget(self.hangup_btn, stretch=2)
        btns.addStretch(1)
        outer.addLayout(btns)

        return panel

    def _build_call_log_strip(self) -> QWidget:
        strip = QFrame()
        strip.setFixedHeight(96)
        strip.setStyleSheet(f"background-color: {theme.BG_PANEL};")
        v = QVBoxLayout(strip)
        v.setContentsMargins(18, 8, 18, 12)
        v.setSpacing(4)

        head = QHBoxLayout()
        title = QLabel("RECENT CALLS")
        title.setObjectName("sectionTitle")
        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("ghostBtn")
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.setFixedWidth(60)
        clear_btn.clicked.connect(self._on_clear_log)
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(clear_btn)
        v.addLayout(head)

        self.log_list = QListWidget()
        self.log_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.log_list.setStyleSheet("background-color: transparent; border: none;")
        v.addWidget(self.log_list)

        return strip

    def _build_status_bar(self) -> QStatusBar:
        sb = QStatusBar()
        sb.setSizeGripEnabled(False)
        sb.setStyleSheet(
            f"QStatusBar {{ background-color: {theme.BG_DEEPEST};"
            f" color: {theme.TEXT_MUTED}; border-top: 1px solid {theme.BORDER}; }}"
            f"QStatusBar::item {{ border: none; }}"
        )
        # Mic level
        self.mic_meter = QProgressBar()
        self.mic_meter.setFixedWidth(140)
        self.mic_meter.setRange(0, 100)
        self.mic_meter.setTextVisible(False)
        self.mic_meter.setFormat("")
        sb.addPermanentWidget(QLabel("  Mic "))
        sb.addPermanentWidget(self.mic_meter)

        self.spk_meter = QProgressBar()
        self.spk_meter.setFixedWidth(140)
        self.spk_meter.setRange(0, 100)
        self.spk_meter.setTextVisible(False)
        sb.addPermanentWidget(QLabel("  Speaker "))
        sb.addPermanentWidget(self.spk_meter)

        sb.addPermanentWidget(QLabel("   "))
        self.lan_ip_label = QLabel(f"LAN IP: {self.manager.local_ip}  ·  Codec: {self.manager.audio.mode.upper()}")
        sb.addPermanentWidget(self.lan_ip_label)
        return sb

    # ---------------------------------------------------------- signals
    def _connect_signals(self) -> None:
        m = self.manager
        m.state_changed.connect(self._on_state_changed)
        m.incoming_call.connect(self._on_incoming_call)
        m.call_accepted.connect(self._on_call_accepted)
        m.call_rejected.connect(self._on_call_rejected)
        m.call_ended.connect(self._on_call_ended)
        m.peer_joined_call.connect(self._on_peer_joined)
        m.peer_left_call.connect(self._on_peer_left)
        m.members_changed.connect(self._on_members_changed)
        m.audio_started.connect(self._on_audio_started)
        m.audio_stopped.connect(self._on_audio_stopped)
        m.info.connect(lambda s: self.statusBar().showMessage("  " + s, 4000))
        m.error.connect(lambda s: self._show_error("Call error", s))

        d = m.discovery
        d.peer_joined.connect(lambda *args: self._refresh_user_list())
        d.peer_updated.connect(lambda *args: self._refresh_user_list())
        d.peer_left.connect(lambda *args: self._refresh_user_list())

        self.call_log.updated.connect(self._on_log_updated)
        # Initial render
        self._on_log_updated(self.call_log.all_entries())

        # Audio levels
        m.audio.input_level.connect(self._on_mic_level)
        m.audio.output_level.connect(self._on_spk_level)

    # ---------------------------------------------------------- handlers
    def _on_username_changed(self) -> None:
        name = self.username_edit.text().strip()
        if not name:
            self.username_edit.setText(self.manager.username)
            return
        self.settings["username"] = name
        config.save_settings(self.settings)
        self.manager.set_username(name)
        self.statusBar().showMessage(f"  Display name set to: {name}", 3000)

    def _refresh_user_list(self) -> None:
        peers = self.manager.discovery.peers()
        # Diff against current rows to avoid rebuilding on every refresh.
        existing_ids = {}
        for i in range(self.user_list.count()):
            item = self.user_list.item(i)
            w = self.user_list.itemWidget(item)
            if w:
                existing_ids[w.peer_id] = (item, w)

        # Remove gone peers
        for pid in list(existing_ids.keys()):
            if pid not in peers:
                item, _ = existing_ids[pid]
                self.user_list.takeItem(self.user_list.row(item))

        # Add new peers + update existing
        for pid, peer in peers.items():
            if pid in existing_ids:
                _, w = existing_ids[pid]
                w.update_peer(peer)
            else:
                item = QListWidgetItem(self.user_list)
                item.setSizeHint(QSize(0, 58))
                w = UserCardWidget(peer)
                w.call_clicked.connect(self._on_call_user)
                w.join_clicked.connect(self._on_join_user)
                self.user_list.addItem(item)
                self.user_list.setItemWidget(item, w)

        self.empty_hint.setVisible(len(peers) == 0)
        if not peers:
            self.empty_hint.setText(
                "No other devices found yet.\n"
                "Make sure other devices are on the same WiFi and running this app."
            )

    def _on_call_user(self, peer_id: str) -> None:
        if self.manager.state != CallManager.STATE_IDLE:
            self._show_error("Busy", "Please hang up the current call first.")
            return
        peer = self.manager.discovery.get_peer(peer_id)
        if not peer:
            self._show_error("User gone", "This user is no longer online.")
            return
        self.call_log.start_call(peer.username, peer.ip, direction="out",
                                 conference=False)
        if not self.manager.call_peer(peer_id):
            self.call_log.end_call(reason="failed")

    def _on_join_user(self, peer_id: str) -> None:
        if self.manager.state != CallManager.STATE_IDLE:
            self._show_error("Busy", "Please hang up the current call first.")
            return
        peer = self.manager.discovery.get_peer(peer_id)
        if not peer:
            self._show_error("User gone", "This user is no longer online.")
            return
        self.call_log.start_call(peer.username + " (room)", peer.ip,
                                 direction="out", conference=True)
        if not self.manager.join_conference(peer_id):
            self.call_log.end_call(reason="failed")

    def _on_start_room(self) -> None:
        if self.manager.state != CallManager.STATE_IDLE:
            self._show_error("Busy", "Please hang up the current call first.")
            return
        if self.manager.start_conference():
            self.call_log.start_call("Conference Room", self.manager.local_ip,
                                     direction="out", conference=True)

    def _on_hangup(self) -> None:
        self.manager.hang_up(reason="user_hangup")

    def _on_mute_toggle(self) -> None:
        new_muted = not self.manager.audio.muted
        self.manager.audio.set_muted(new_muted)
        self.settings["muted"] = new_muted
        config.save_settings(self.settings)
        if new_muted:
            self.mute_btn.setText("🔇  Unmute")
            self.mute_btn.setStyleSheet(
                f"background-color: {theme.DANGER}; color: white; border: 1px solid {theme.DANGER}; border-radius: 6px;"
            )
        else:
            self.mute_btn.setText("🎤  Mute")
            self.mute_btn.setStyleSheet("")  # revert to QSS (ghostBtn)

    def _on_volume_changed(self, value: int) -> None:
        self.manager.audio.set_volume(value)
        self.vol_value_label.setText(f"{value}%")
        self.settings["volume"] = value
        config.save_settings(self.settings)

    # -------- state transitions
    def _on_state_changed(self, state: str) -> None:
        self.status_dot.set_state(state)
        in_call = state == CallManager.STATE_IN_CALL
        calling = state == CallManager.STATE_CALLING

        self.hangup_btn.setEnabled(in_call or calling)
        self.mute_btn.setEnabled(in_call)
        self.volume_slider.setEnabled(in_call)
        self.start_room_btn.setEnabled(state == CallManager.STATE_IDLE)

        label_map = {
            CallManager.STATE_IDLE: ("No active call", "Pick a user on the left and press Call, or start a conference room."),
            CallManager.STATE_CALLING: ("Calling…", "Waiting for the other side to answer."),
            CallManager.STATE_INCOMING: ("Incoming call", "An user is calling you."),
            CallManager.STATE_IN_CALL: ("In call", "You are connected."),
        }
        title, sub = label_map.get(state, ("", ""))
        self.state_title.setText(title)
        self.state_subtitle.setText(sub)
        self.status_label.setText(state.replace("_", " ").title())

        if state == CallManager.STATE_IN_CALL:
            self._current_call_started_at = time.time()
            if not self._duration_timer.isActive():
                self._duration_timer.start()
            self.duration_label.setVisible(True)
            self._update_duration()
        else:
            self._duration_timer.stop()
            self.duration_label.setVisible(False)
            self.duration_label.setText("")

    def _on_incoming_call(self, call_id: str, name: str, ip: str,
                          conference: bool) -> None:
        self._active_call_id = call_id
        kind = "conference room" if conference else "call"
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Question)
        msg.setWindowTitle("Incoming call")
        msg.setText(f"{name} ({ip}) is calling you.")
        msg.setInformativeText(f"Answer this {kind}?")
        accept = msg.addButton("Accept", QMessageBox.AcceptRole)
        reject = msg.addButton("Reject", QMessageBox.RejectRole)
        msg.exec_()
        if msg.clickedButton() is accept:
            self.call_log.start_call(name, ip, direction="in",
                                     conference=conference)
            self.manager.accept_incoming(call_id)
        else:
            self.manager.reject_incoming(call_id, reason="declined")
            self.call_log.end_call(reason="declined")
            self._active_call_id = None

    def _on_call_accepted(self, call_id: str) -> None:
        self.statusBar().showMessage("  Call answered", 3000)

    def _on_call_rejected(self, call_id: str, reason: str) -> None:
        if reason == "timeout":
            self.statusBar().showMessage("  No answer (timeout)", 4000)
            self.call_log.end_call(reason="timeout")
        elif reason == "busy":
            self.statusBar().showMessage("  User is busy", 4000)
            self.call_log.end_call(reason="busy")
        elif reason == "no_room":
            self.statusBar().showMessage("  That user isn't hosting a room", 4000)
            self.call_log.end_call(reason="no_room")
        elif reason == "room_full":
            self.statusBar().showMessage("  Room is full", 4000)
            self.call_log.end_call(reason="room_full")
        elif reason == "declined":
            self.statusBar().showMessage("  Call declined", 4000)
        else:
            self.statusBar().showMessage(f"  Call rejected: {reason}", 4000)
            self.call_log.end_call(reason=reason)

    def _on_call_ended(self, reason: str) -> None:
        self.call_log.end_call(reason=reason)
        self._active_call_id = None

    def _on_peer_joined(self, name: str, ip: str) -> None:
        self.statusBar().showMessage(f"  {name} joined", 3000)

    def _on_peer_left(self, name: str, ip: str) -> None:
        self.statusBar().showMessage(f"  {name} left", 3000)

    def _on_members_changed(self, members: list) -> None:
        # Clear current bubbles
        while self.members_layout.count():
            child = self.members_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        # Add self
        self_bubble = MemberBubble(self.manager.username, "", is_self=True)
        self.members_layout.addWidget(self_bubble)

        # Add each member
        for pid, name, ip in members:
            bubble = MemberBubble(name, ip)
            self.members_layout.addWidget(bubble)

        self.members_layout.addStretch(1)

    def _on_audio_started(self) -> None:
        # Apply current UI state to the engine
        self.manager.audio.set_volume(self.volume_slider.value())
        self.manager.audio.set_muted(self.settings.get("muted", False))
        if self.settings.get("muted", False):
            self.mute_btn.setText("🔇  Unmute")
            self.mute_btn.setStyleSheet(
                f"background-color: {theme.DANGER}; color: white; border: 1px solid {theme.DANGER}; border-radius: 6px;"
            )
        else:
            self.mute_btn.setText("🎤  Mute")
            self.mute_btn.setStyleSheet("")

    def _on_audio_stopped(self) -> None:
        self.mic_meter.setValue(0)
        self.spk_meter.setValue(0)

    def _on_mic_level(self, lvl: float) -> None:
        self.mic_meter.setValue(int(lvl * 100))

    def _on_spk_level(self, lvl: float) -> None:
        self.spk_meter.setValue(int(lvl * 100))

    def _on_log_updated(self, entries: list) -> None:
        self.log_list.clear()
        if not entries:
            item = QListWidgetItem("  No calls yet.")
            item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            self.log_list.addItem(item)
            return
        from datetime import datetime
        for e in entries[-15:][::-1]:
            ts = datetime.fromtimestamp(e.get("started_at", 0)).strftime("%H:%M")
            dur = e.get("duration_sec", 0)
            dur_str = f"{dur // 60}m {dur % 60}s" if dur else "—"
            arrow = "↗" if e.get("direction") == "out" else "↙"
            conf = " (room)" if e.get("conference") else ""
            reason = e.get("ended_reason", "")
            tail = f"  [{reason}]" if reason and reason not in ("user_hangup", "remote_hangup") else ""
            line = f"  {arrow} {e.get('peer_name','?')}{conf}  ·  {ts}  ·  {dur_str}{tail}"
            item = QListWidgetItem(line)
            item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            self.log_list.addItem(item)

    def _on_clear_log(self) -> None:
        self.call_log.clear()

    # ---------------------------------------------------------- helpers
    def _update_duration(self) -> None:
        if not self._current_call_started_at:
            return
        secs = int(time.time() - self._current_call_started_at)
        self.duration_label.setText(
            f"⏱  {secs // 60:02d}:{secs % 60:02d}"
        )

    def _show_error(self, title: str, msg: str) -> None:
        QMessageBox.warning(self, title, msg)

    # ---------------------------------------------------------- shutdown
    def closeEvent(self, event) -> None:
        try:
            self.manager.stop()
        except Exception:
            pass
        event.accept()
