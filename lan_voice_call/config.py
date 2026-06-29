"""Application configuration constants.

All values tuned for low-latency LAN voice calls (target ~40-60 ms mouth-to-ear).
"""
import os
import uuid
import socket
import getpass
import json
from pathlib import Path

APP_NAME = "LAN Voice Call"
APP_VERSION = "1.0.0"

# -------- Network ports --------
DISCOVERY_BROADCAST_PORT = 50000     # UDP broadcast listener
DISCOVERY_MULTICAST_PORT = 50001     # UDP multicast listener
DISCOVERY_MULTICAST_GROUP = "224.0.0.1"
SIGNALING_PORT = 50002               # TCP signaling (call setup / hangup / room)
AUDIO_PORT = 50010                   # UDP audio stream

# -------- Presence / Discovery --------
PRESENCE_INTERVAL = 2.0              # seconds between presence beacons
USER_TIMEOUT = 6.5                   # expire a user after this many seconds silent
CLEANUP_INTERVAL = 1.0               # how often to scan for expired users

# -------- Audio --------
AUDIO_SAMPLE_RATE = 48000            # Opus native rate
AUDIO_CHANNELS = 1                   # mono
AUDIO_FRAME_MS = 20                  # 20 ms frames -> low latency
AUDIO_FRAME_SAMPLES = AUDIO_SAMPLE_RATE * AUDIO_FRAME_MS // 1000  # 960
AUDIO_DTYPE = "int16"

# -------- Opus codec --------
OPUS_APPLICATION = "voip"            # optimized for voice
OPUS_BITRATE = 32000                 # 32 kbps - clean voice on LAN
OPUS_COMPLEXITY = 5                  # 1-10, 5 = good balance
OPUS_PACKET_LOSS = 5                 # % expected loss -> encoder tunes FEC
OPUS_DTX = True                      # silence -> tiny packets, saves CPU

# -------- Call / UI --------
CALL_TIMEOUT = 30                    # seconds before an unanswered call auto-cancels
CONFERENCE_MAX_PEERS = 8             # safety cap on conference size

# -------- Persistence --------
APP_DATA_DIR = Path.home() / ".lan_voice_call"
APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_FILE = APP_DATA_DIR / "settings.json"
CALL_LOG_FILE = APP_DATA_DIR / "call_log.json"


def get_local_ip() -> str:
    """Determine the LAN-facing IP address of this machine.

    Connects a UDP socket to a public IP (no packets actually sent) so the OS
    picks the interface that would be used for outbound traffic. Falls back
    to 127.0.0.1 if anything fails.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # 8.8.8.8 is just a target; no packet is sent for SOCK_DGRAM connect()
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        if ip:
            return ip
    except Exception:
        pass
    try:
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    return "127.0.0.1"


def default_username() -> str:
    """Pick a sensible default display name on first launch."""
    try:
        name = getpass.getuser()
        if name and name.strip():
            return name[:24]
    except Exception:
        pass
    try:
        return socket.gethostname()[:24]
    except Exception:
        return "User"


def load_settings() -> dict:
    """Load persisted user settings (username, last volume)."""
    defaults = {"username": default_username(), "volume": 80, "muted": False}
    try:
        if SETTINGS_FILE.exists():
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                defaults.update({k: v for k, v in data.items() if k in defaults})
    except Exception:
        pass
    return defaults


def save_settings(settings: dict) -> None:
    """Persist user settings."""
    try:
        SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    except Exception:
        pass


def machine_id() -> str:
    """Stable per-machine identifier for presence deduplication."""
    cached = APP_DATA_DIR / "machine_id"
    if cached.exists():
        try:
            return cached.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    new_id = str(uuid.uuid4())
    try:
        cached.write_text(new_id, encoding="utf-8")
    except Exception:
        pass
    return new_id
