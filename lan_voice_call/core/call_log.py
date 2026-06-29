"""Call log persistence - keeps a JSON file with the last ~100 calls."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import List

from PyQt5.QtCore import QObject, pyqtSignal

from .. import config


class CallLog(QObject):
    """Persisted call history.

    Each entry: {"id", "peer_name", "peer_ip", "direction",
                 "started_at", "duration_sec", "ended_reason"}
    """

    updated = pyqtSignal(list)  # list of entries (newest first)

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._entries: List[dict] = []
        self._active: dict | None = None  # currently-open call record
        self._load()

    def _load(self) -> None:
        try:
            if config.CALL_LOG_FILE.exists():
                data = json.loads(config.CALL_LOG_FILE.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self._entries = [e for e in data if isinstance(e, dict)]
        except Exception:
            self._entries = []

    def _save(self) -> None:
        try:
            config.CALL_LOG_FILE.write_text(
                json.dumps(self._entries[-100:], indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def start_call(self, peer_name: str, peer_ip: str, direction: str,
                   conference: bool = False) -> None:
        """direction: 'out' | 'in'. Marks the call as active for end_call()."""
        with self._lock:
            self._active = {
                "id": f"{int(time.time())}-{peer_ip}",
                "peer_name": peer_name,
                "peer_ip": peer_ip,
                "direction": direction,
                "conference": bool(conference),
                "started_at": time.time(),
                "duration_sec": 0,
                "ended_reason": "",
            }

    def end_call(self, reason: str = "") -> None:
        with self._lock:
            if not self._active:
                return
            self._active["duration_sec"] = int(
                time.time() - self._active["started_at"]
            )
            self._active["ended_reason"] = reason
            self._entries.append(self._active)
            self._entries = self._entries[-100:]
            snapshot = list(reversed(self._entries))
            self._active = None
            self._save()
        self.updated.emit(snapshot)

    def all_entries(self) -> List[dict]:
        with self._lock:
            return list(reversed(self._entries))

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._save()
        self.updated.emit([])
