# LAN Voice Call

A fully offline peer-to-peer voice calling app for local networks.
No internet, no servers, no accounts — just two or more PCs on the same
WiFi, each running this app.

![status](https://img.shields.io/badge/status-ready-success) ![platform](https://img.shields.io/badge/platform-Windows%2010%2F11-blue) ![offline](https://img.shields.io/badge/offline-100%25-brightgreen)

---

## ✨ Features

- **Fully offline** — no internet connection is ever needed. Audio, signaling,
  and peer discovery all happen over the local network.
- **Multi-party conference** — start a room, others join; up to 8 people can
  talk at once in mesh mode.
- **1-to-1 calls** — pick a user, click Call, talk.
- **Auto-discovery** — other PCs running the app on the same WiFi appear
  automatically in the user list (UDP broadcast + multicast).
- **Low latency** — 20 ms Opus frames at 32 kbps, target ~50 ms mouth-to-ear.
- **Clean dark UI** — modern teal accent, level meters, in-call duration.
- **Mute mic** & **volume slider** during calls.
- **Custom display name** (or use your Windows user name by default).
- **Call log** — recent calls with name, direction, duration, outcome.
- **Graceful degradation** — if Opus isn't available, falls back to raw PCM
  (same functionality, more bandwidth).

---

## 🚀 Quick Start (end users)

You only need the built `LANVoiceCall` folder.

1. **Copy the `LANVoiceCall` folder** to every PC that should be able to call
   each other. They must all be on the **same WiFi network**.
2. **Double-click `LANVoiceCall.exe`** on each PC.
   - Windows SmartScreen may warn it's an "unrecognized app". Click
     **More info** → **Run anyway**. (The app is not code-signed; this is
     normal for personal / open-source projects.)
3. The app shows your machine name as your display name. Click the name
   field at the top to change it.
4. Other PCs appear in the **USERS ON THIS LAN** list within a few seconds.
5. Click **Call** next to a user to start a 1-to-1 call, or click
   **Start Conference Room** to host a multi-party call and have others
   click **Join Room** next to your name.

> 💡 **Tip**: If no users appear, make sure Windows Firewall allows the app
> on private networks. The first time you run it, Windows will ask — pick
> **Private networks** (not Public).

---

## 🛠 Build Your Own .exe (developers)

### Prerequisites

- **Windows 10 or 11**
- **Python 3.10, 3.11, or 3.12** — get it from <https://python.org>.
  During install, **tick "Add Python to PATH"**.
- Internet access for the first build (to download pip packages and libopus).

### Steps

1. Download or clone this project to a folder on your PC.
2. Open **Command Prompt** or **PowerShell** in that folder.
3. Run:
   ```bat
   build.bat
   ```
4. The script will:
   - Install Python dependencies (`PyQt5`, `sounddevice`, `opuslib`, `pyinstaller`)
   - Download `opus.dll` (if missing)
   - Build the exe with PyInstaller
   - Place the result in `dist\LANVoiceCall\`
5. When it says **BUILD COMPLETE**, your app is at:
   ```
   dist\LANVoiceCall\LANVoiceCall.exe
   ```
6. **Distribute**: zip the entire `LANVoiceCall` folder and send it to other
   PCs. They don't need Python installed — everything is bundled.

---

## 📁 Project Layout

```
lan_voice_call/
├── lan_voice_call/                # Python source
│   ├── __init__.py
│   ├── _opus_loader.py            # Windows: preloads opus.dll from bundle
│   ├── config.py                  # Constants, ports, settings persistence
│   ├── main.py                    # Qt application bootstrap
│   ├── core/
│   │   ├── __init__.py
│   │   ├── discovery.py           # UDP broadcast + multicast peer discovery
│   │   ├── signaling.py           # TCP signaling (call setup, hangup, room)
│   │   ├── audio_engine.py        # Capture + Opus + UDP + decode + mix + playback
│   │   ├── call_manager.py        # State machine for 1-to-1 + conference mesh
│   │   └── call_log.py            # Recent-calls JSON persistence
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── theme.py               # Dark Qt stylesheet
│   │   └── main_window.py         # Main GUI (user list, call panel, log)
│   └── requirements.txt
├── run.py                         # PyInstaller entry point (no relative imports)
├── LANVoiceCall.spec              # PyInstaller build spec
├── build.bat                      # One-click Windows build script
└── README.md                      # This file
```

---

## ⚙️ How It Works

### Network topology

```
+-------+                       +-------+
| Alice | ──── audio (UDP) ───> |  Bob  |
|       | <── audio (UDP) ───── |       |
|       | ─── signaling (TCP) ─> |       |
+-------+                       +-------+
     ↘                            ↙
       └── broadcast/multicast ─┘
           (UDP 50000/50001, every 2s)
```

- **Discovery** (UDP 50000 broadcast + UDP 50001 multicast 224.0.0.1):
  each peer announces itself every 2 seconds with `{id, username, ip, ports}`.
  Peers expire after 6.5 s of silence.
- **Signaling** (TCP 50002): short-lived connections for call_request,
  call_accept, call_reject, call_end, join_room, room_members, room_new_peer.
- **Audio** (UDP 50010): direct peer-to-peer Opus packets, 20 ms frames,
  ~32 kbps. Each packet has a 5-byte header `[4-byte seq][1-byte codec]`.

### Conference mesh

When Alice starts a room and Bob and Carol join:
- Bob sends `join_room` to Alice.
- Alice replies with `room_members` listing all current members.
- Bob opens audio streams to Alice and (when she joins) Carol.
- Alice notifies Carol via `room_new_peer` so Carol also opens audio to Bob.
- Each peer mixes all incoming audio streams in the playback callback.

### Latency budget

| Stage | Time |
|---|---|
| Capture (20 ms frame) | 20 ms |
| Opus encode | <1 ms |
| UDP over WiFi (1 hop) | 1-3 ms |
| Opus decode | <1 ms |
| Jitter buffer | 0-20 ms |
| Playback (20 ms frame) | 20 ms |
| **Total mouth-to-ear** | **~50 ms** |

### Codec

- 48 kHz mono Opus in VOIP mode, 32 kbps, complexity 5, 5% FEC, DTX on.
- Silence produces tiny (~6 byte) packets via DTX, saving CPU and bandwidth.
- Falls back to raw 16-bit PCM if opuslib/libopus can't load.

---

## 🔧 Troubleshooting

### "Cannot bind signaling port 50002"

Another instance of LAN Voice Call is already running. Close it (check the
system tray) and try again.

### No users appear in the list

1. Make sure all PCs are on the **same WiFi** (not Ethernet + WiFi mix on a
   guest network — many routers isolate wireless clients).
2. **Allow the app through Windows Firewall**: Settings → Privacy & security
   → Windows Security → Firewall & network protection → Allow an app
   through firewall → find `LANVoiceCall.exe` → tick **Private**.
3. Some routers block UDP broadcast between wired and wireless clients.
   If you're mixing WiFi and Ethernet, ask the router admin to enable
   "AP isolation: off" or "client isolation: off".
4. As a workaround, you can usually still call a specific user via their IP
   (manual entry is not exposed in the UI yet — ping me if you need it).

### Audio is choppy / robotic

- Close other apps that use the mic (Zoom, Teams, Discord).
- Plug in a USB headset — built-in laptop mics and speakers can cause echo.
- If you're on a weak CPU, edit `config.py` and lower `OPUS_COMPLEXITY` to 3
  or increase `AUDIO_FRAME_MS` to 40 (more latency, less CPU).

### Other side can't hear me

- Click **Mute** to toggle it off (it may be muted from a previous call).
- Check Windows sound settings: right-click the speaker icon → Sound
  settings → make sure the right input device is selected.
- If you have multiple audio devices, set the correct default input in
  Windows before launching the app.

### "No audio input or output device found"

- The app needs at least one working audio device. Plug in headphones or
  a USB headset and try again.
- If you're using a virtual audio cable, make sure it's started.

### The app freezes when I hang up

- This can happen if Windows holds the audio device. Wait ~2 seconds; if
  it doesn't recover, kill it via Task Manager and relaunch.

### Build fails: "opus.dll not found"

The `build.bat` script tries to download opus.dll automatically. If that
fails (corporate proxy, etc.):
1. Go to <https://opus-codec.org/downloads/> or
   <https://github.com/xiph/opus/releases>.
2. Download the latest Windows binary.
3. Extract `opus.dll` (or `libopus-0.dll`) and place it as `dll\opus.dll`
   inside the project folder.
4. Re-run `build.bat`.

---

## 🛡 Privacy & Security

- **No telemetry**: the app does not phone home. There is no analytics,
  no crash reporter, no auto-update check.
- **No accounts**: nothing is ever stored on a server.
- **Local data**: settings and call log are stored at
  `%USERPROFILE%\.lan_voice_call\`. Delete that folder to wipe everything.
- **Audio encryption**: not included in v1.0. Audio packets travel in plain
  Opus over your LAN; anyone running Wireshark on the same network could
  capture them. For a private setting (home WiFi) this is fine; for a
  hostile LAN, run a VPN between the participants.

---

## ❓ FAQ

**Q: Does it work over the internet?**
A: No, by design. It only finds peers on the same Layer-2 network. To use
   it over the internet, run a VPN (like Tailscale or ZeroTier) first so
   both PCs share a virtual LAN.

**Q: How many people can join a conference?**
A: Up to 8 (hard cap in `config.py` — `CONFERENCE_MAX_PEERS`). Beyond that,
   mesh P2P doesn't scale; you'd want an SFU server.

**Q: Why does it use ~50 KB/s of bandwidth?**
A: 32 kbps Opus × both directions = 64 kbps = 8 KB/s. Plus overhead. On a
   LAN this is negligible.

**Q: Can I run it on macOS / Linux?**
A: The Python source runs on any platform with PyQt5 + PortAudio + libopus.
   The provided `build.bat` is Windows-only; for macOS/Linux, run
   `pip install -r lan_voice_call/requirements.txt` and then
   `python -m lan_voice_call`.

**Q: Will my antivirus flag it?**
A: Some AVs are suspicious of PyInstaller-bundled exes. If yours flags it,
   whitelist the `LANVoiceCall` folder. The source code is open for
   inspection — there is nothing malicious in it.

---

## 📜 License

MIT License. See `LICENSE` file. Use it, modify it, share it.

---

## 🙏 Credits

Built with:
- [PyQt5](https://www.riverbankcomputing.com/software/pyqt/) — GUI framework
- [sounddevice](https://python-sounddevice.readthedocs.io/) — PortAudio bindings
- [opuslib](https://github.com/ambv/opuslib) — Opus codec bindings
- [Xiph.Org Opus](https://opus-codec.org/) — the Opus audio codec
- [PyInstaller](https://pyinstaller.org/) — Python → exe bundler
