"""Real-time audio engine: capture -> Opus encode -> UDP -> Opus decode -> mix -> playback.

Design goals
------------
* Very low latency: 20 ms frames, 48 kHz mono, Opus @ 32 kbps in VOIP mode.
* Multi-peer mixing: each peer has its own jitter buffer; the playback callback
  sums one frame from every peer to produce the output mix.
* Graceful degradation: if no input device, the engine still plays audio;
  if no output device, it still sends. If Opus init fails, the engine
  transparently falls back to raw PCM (larger packets, same call quality).

Packet format
-------------
    [4 bytes seq (big-endian uint32)] [1 byte codec 'O'/'P'] [payload]

Thread layout
-------------
* Capture callback (PA thread): encode + UDP send to every peer.
* Receive thread: UDP recvfrom -> decode -> per-peer jitter buffer.
* Playback callback (PA thread): pull one frame per peer, sum, apply volume.
"""
from __future__ import annotations

import socket
import struct
import threading
import time
from collections import deque
from typing import Dict, Optional, Tuple

import numpy as np
from PyQt5.QtCore import QObject, pyqtSignal

from .. import config

try:
    import opuslib
    _OPUS_AVAILABLE = True
except Exception:
    _OPUS_AVAILABLE = False

try:
    import sounddevice as sd
    _SD_AVAILABLE = True
except Exception:
    _SD_AVAILABLE = False


# ---------------------------------------------------------------------------
# Codec helpers
# ---------------------------------------------------------------------------
class Codec:
    """Opus encode/decode with automatic PCM fallback."""

    def __init__(self):
        self.use_opus = _OPUS_AVAILABLE
        self.encoder = None
        self.decoder = None
        if self.use_opus:
            try:
                self.encoder = opuslib.Encoder(
                    config.AUDIO_SAMPLE_RATE,
                    config.AUDIO_CHANNELS,
                    opuslib.APPLICATION_VOIP,
                )
                self.encoder.bitrate = config.OPUS_BITRATE
                self.encoder.complexity = config.OPUS_COMPLEXITY
                self.encoder.packet_loss_perc = config.OPUS_PACKET_LOSS
                self.encoder.dtx = 1 if config.OPUS_DTX else 0
                self.decoder = opuslib.Decoder(
                    config.AUDIO_SAMPLE_RATE, config.AUDIO_CHANNELS
                )
            except Exception:
                self.use_opus = False
                self.encoder = None
                self.decoder = None
        self.frame_bytes_pcm = (
            config.AUDIO_FRAME_SAMPLES * config.AUDIO_CHANNELS * 2  # int16
        )

    def encode(self, pcm: bytes) -> bytes:
        if self.use_opus and self.encoder:
            try:
                return self.encoder.encode(pcm, config.AUDIO_FRAME_SAMPLES)
            except Exception:
                try:
                    # Re-init on transient failure.
                    self.encoder = opuslib.Encoder(
                        config.AUDIO_SAMPLE_RATE, config.AUDIO_CHANNELS,
                        opuslib.APPLICATION_VOIP,
                    )
                    self.encoder.bitrate = config.OPUS_BITRATE
                    self.encoder.complexity = config.OPUS_COMPLEXITY
                    return self.encoder.encode(pcm, config.AUDIO_FRAME_SAMPLES)
                except Exception:
                    return pcm
        return pcm

    def decode(self, data: bytes) -> bytes:
        if self.use_opus and self.decoder:
            try:
                return self.decoder.decode(data, config.AUDIO_FRAME_SAMPLES)
            except Exception:
                # Corrupt / wrong-size packet -> silence.
                return b"\x00" * self.frame_bytes_pcm
        # PCM fallback: ensure length matches expected frame.
        if len(data) == self.frame_bytes_pcm:
            return data
        return b"\x00" * self.frame_bytes_pcm

    @property
    def mode(self) -> str:
        return "opus" if self.use_opus else "pcm"


# ---------------------------------------------------------------------------
# Peer receive state
# ---------------------------------------------------------------------------
class PeerStream:
    """Per-peer jitter buffer + sequence tracking."""

    __slots__ = ("peer_id", "ip", "port", "jitter", "last_seq", "last_recv", "lock")

    def __init__(self, peer_id: str, ip: str, port: int):
        self.peer_id = peer_id
        self.ip = ip
        self.port = port
        # 200 ms jitter buffer (10 frames * 20 ms).
        self.jitter: deque = deque(maxlen=10)
        self.last_seq: int = -1
        self.last_recv: float = time.time()
        self.lock = threading.Lock()


# ---------------------------------------------------------------------------
# Audio engine
# ---------------------------------------------------------------------------
class AudioEngine(QObject):
    """Drives capture, encoding, UDP send/recv, decode, mix and playback.

    Signals:
        input_level (float 0..1)  - microphone level, ~10 Hz
        output_level (float 0..1) - speaker level, ~10 Hz
        error (str)               - user-facing error message
    """

    input_level = pyqtSignal(float)
    output_level = pyqtSignal(float)
    error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.codec = Codec()

        # Peer state
        self._peers_by_id: Dict[str, PeerStream] = {}
        self._peers_by_ip: Dict[str, PeerStream] = {}
        self._peers_lock = threading.RLock()

        # UDP socket for inbound audio
        self._udp: Optional[socket.socket] = None
        self._recv_thread: Optional[threading.Thread] = None

        # Capture/playback
        self._stream_in: Optional["sd.InputStream"] = None
        self._stream_out: Optional["sd.OutputStream"] = None
        self._running = threading.Event()

        # State
        self._muted = False
        self._volume = 1.0  # 0..1 multiplier on output

        # Level metering (debounced)
        self._last_in_emit = 0.0
        self._last_out_emit = 0.0

    # ------------------------------------------------------------------ API
    @property
    def mode(self) -> str:
        return self.codec.mode

    @property
    def muted(self) -> bool:
        return self._muted

    def set_muted(self, muted: bool) -> None:
        self._muted = bool(muted)

    def set_volume(self, percent: int) -> None:
        """Volume as 0..100 integer."""
        self._volume = max(0, min(100, int(percent))) / 100.0

    def start(self) -> bool:
        """Open UDP socket, input/output streams. Returns True on success."""
        if self._running.is_set():
            return True
        if not _SD_AVAILABLE:
            self.error.emit("PortAudio is not available - audio will not work.")
            return False

        # UDP socket
        try:
            self._udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                self._udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except (AttributeError, OSError):
                pass
            self._udp.bind(("0.0.0.0", config.AUDIO_PORT))
            self._udp.settimeout(0.5)
        except OSError as e:
            self.error.emit(f"Cannot bind audio port {config.AUDIO_PORT}: {e}")
            return False

        self._running.set()

        # Receive thread
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()

        # Output stream first so we can hear peers immediately.
        try:
            self._stream_out = sd.OutputStream(
                samplerate=config.AUDIO_SAMPLE_RATE,
                blocksize=config.AUDIO_FRAME_SAMPLES,
                dtype=config.AUDIO_DTYPE,
                channels=config.AUDIO_CHANNELS,
                callback=self._playback_callback,
            )
            self._stream_out.start()
        except Exception:
            # Playback failure is non-fatal: keep mic working.
            self._stream_out = None

        # Input stream
        try:
            self._stream_in = sd.InputStream(
                samplerate=config.AUDIO_SAMPLE_RATE,
                blocksize=config.AUDIO_FRAME_SAMPLES,
                dtype=config.AUDIO_DTYPE,
                channels=config.AUDIO_CHANNELS,
                callback=self._capture_callback,
            )
            self._stream_in.start()
        except Exception:
            self._stream_in = None
            if self._stream_out is None:
                self.error.emit("No audio input or output device found.")
                self.stop()
                return False
            # else: half-duplex (can hear, can't speak) - allowed.
        return True

    def stop(self) -> None:
        self._running.clear()
        if self._stream_in:
            try:
                self._stream_in.stop()
                self._stream_in.close()
            except Exception:
                pass
            self._stream_in = None
        if self._stream_out:
            try:
                self._stream_out.stop()
                self._stream_out.close()
            except Exception:
                pass
            self._stream_out = None
        if self._udp:
            try:
                self._udp.close()
            except Exception:
                pass
            self._udp = None
        with self._peers_lock:
            self._peers_by_id.clear()
            self._peers_by_ip.clear()

    def add_peer(self, peer_id: str, ip: str, port: int) -> None:
        """Register a peer to send audio to and accept audio from."""
        with self._peers_lock:
            existing = self._peers_by_id.get(peer_id)
            if existing:
                # Update IP/port in case of change (DHCP renewal, etc.)
                if existing.ip != ip:
                    self._peers_by_ip.pop(existing.ip, None)
                    existing.ip = ip
                    self._peers_by_ip[ip] = existing
                existing.port = port
                existing.last_recv = time.time()
            else:
                ps = PeerStream(peer_id, ip, int(port))
                self._peers_by_id[peer_id] = ps
                self._peers_by_ip[ip] = ps

    def remove_peer(self, peer_id: str) -> None:
        with self._peers_lock:
            ps = self._peers_by_id.pop(peer_id, None)
            if ps:
                self._peers_by_ip.pop(ps.ip, None)

    def has_peers(self) -> bool:
        with self._peers_lock:
            return len(self._peers_by_id) > 0

    def peer_count(self) -> int:
        with self._peers_lock:
            return len(self._peers_by_id)

    # -------------------------------------------------------------- threads
    def _capture_callback(self, indata, frames, time_info, status) -> None:
        """PortAudio input callback: encode + UDP send to all peers."""
        if not self._running.is_set():
            return
        try:
            pcm_bytes = indata.tobytes()
            if self._muted:
                pcm_bytes = b"\x00" * len(pcm_bytes)

            seq = int(time.time() * 1000) & 0xFFFFFFFF
            payload = self.codec.encode(pcm_bytes)
            header = struct.pack(">IB", seq, ord(self.codec.mode[0].upper()))
            packet = header + payload

            # Emit input level ~10 Hz
            now = time.time()
            if now - self._last_in_emit > 0.1:
                lvl = float(np.abs(indata).max() / 32768.0)
                self._last_in_emit = now
                self.input_level.emit(min(1.0, lvl * 1.5))

            with self._peers_lock:
                targets = [(ps.ip, ps.port) for ps in self._peers_by_id.values()]
            for ip, port in targets:
                try:
                    self._udp.sendto(packet, (ip, port))
                except OSError:
                    pass
        except Exception:
            # Never raise from a PortAudio callback.
            pass

    def _recv_loop(self) -> None:
        """UDP recv loop: decode each packet, push PCM into per-peer jitter."""
        while self._running.is_set() and self._udp:
            try:
                data, addr = self._udp.recvfrom(8192)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data:
                continue
            self._handle_packet(data, addr[0] if addr else "")

    def _handle_packet(self, data: bytes, src_ip: str) -> None:
        if len(data) < 5:
            return
        try:
            seq, codec_id = struct.unpack(">IB", data[:5])
        except struct.error:
            return
        payload = data[5:]

        with self._peers_lock:
            ps = self._peers_by_ip.get(src_ip)
        if ps is None:
            return  # Unknown peer - drop.

        # Out-of-order / duplicate detection (drop old packets).
        with ps.lock:
            if ps.last_seq != -1:
                # Wraparound-safe comparison: if seq is "older" by more than
                # half the uint32 space, treat it as a wraparound forward.
                diff = (seq - ps.last_seq) & 0xFFFFFFFF
                if diff > 0x7FFFFFFF:
                    # seq is older -> drop.
                    return
            ps.last_seq = seq
            ps.last_recv = time.time()

        pcm = self.codec.decode(payload)
        try:
            pcm_arr = np.frombuffer(pcm, dtype=np.int16).copy()
        except ValueError:
            return
        with ps.lock:
            ps.jitter.append(pcm_arr)

    def _playback_callback(self, outdata, frames, time_info, status) -> None:
        """PortAudio output callback: sum one frame per peer -> speaker."""
        try:
            n = config.AUDIO_FRAME_SAMPLES
            acc = np.zeros(n, dtype=np.int32)

            with self._peers_lock:
                streams = list(self._peers_by_id.values())

            for ps in streams:
                with ps.lock:
                    if ps.jitter:
                        frame = ps.jitter.popleft()
                    else:
                        continue  # No data this tick -> silence for this peer.
                # Pad/trim to n
                if len(frame) >= n:
                    acc += frame[:n].astype(np.int32)
                else:
                    acc[: len(frame)] += frame.astype(np.int32)

            # Soft clip + apply volume.
            mixed = acc.clip(-32768, 32767).astype(np.int16)
            if self._volume != 1.0:
                mixed = (
                    mixed.astype(np.float32) * self._volume
                ).clip(-32768, 32767).astype(np.int16)
            outdata[:, 0] = mixed

            # Output level metering (debounced ~10 Hz).
            now = time.time()
            if now - self._last_out_emit > 0.1:
                lvl = float(np.abs(mixed).max() / 32768.0)
                self._last_out_emit = now
                self.output_level.emit(min(1.0, lvl * 1.2))
        except Exception:
            outdata[:] = 0
