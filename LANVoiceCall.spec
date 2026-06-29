# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for LAN Voice Call.

Produces a single-folder distribution (faster startup than onefile, no
extraction to %TEMP%). Users can zip the folder and ship it to other PCs.

Build:
    pyinstaller LANVoiceCall.spec

The resulting app is in dist/LANVoiceCall/LANVoiceCall.exe
"""
import os
import sys
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_data_files

block_cipher = None

# Collect native DLLs that PyInstaller misses by default:
# - PortAudio (sounddevice backend)
# - Qt plugins (PyQt5)
hiddenimports = [
    "sounddevice",
    "_sounddevice_data",
    "opuslib",
    "numpy",
    "PyQt5",
    "PyQt5.QtCore",
    "PyQt5.QtGui",
    "PyQt5.QtWidgets",
    "PyQt5.sip",
]

# sounddevice bundles PortAudio in _sounddevice_data
datas = []
datas += collect_data_files("sounddevice", include_py_files=False)
datas += collect_data_files("PyQt5", include_py_files=False)

binaries = []
binaries += collect_dynamic_libs("sounddevice")
binaries += collect_dynamic_libs("PyQt5")
# On Windows, opuslib loads libopus-0.dll via ctypes.util.find_library.
# We bundle it explicitly below; the dll must be on PATH at runtime.
# The build.bat script downloads libopus-0.dll and places it in dll/libopus.dll.

# Add any *.dll found in ./dll/ (libopus etc.) - Windows only.
_dll_dir = os.path.join(SPECPATH, "dll")
if os.path.isdir(_dll_dir):
    for fname in os.listdir(_dll_dir):
        if fname.lower().endswith(".dll"):
            binaries.append((os.path.join(_dll_dir, fname), "."))

a = Analysis(
    ["run.py"],
    pathex=[SPECPATH],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Trim unused stuff for a smaller bundle.
        "tkinter",
        "matplotlib",
        "scipy",
        "pandas",
        "PyQt5.QtWebEngineCore",
        "PyQt5.QtWebEngineWidgets",
        "PyQt5.QtWebChannel",
        "PyQt5.QtMultimedia",
        "PyQt5.QtSql",
        "PyQt5.QtTest",
        "PyQt5.QtBluetooth",
        "PyQt5.QtNetwork",
        "PyQt5.QtPositioning",
        "PyQt5.QtSensors",
        "PyQt5.QtSerialPort",
        "PyQt5.QtSvg",
        "PyQt5.QtXml",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LANVoiceCall",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI app, no console window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(SPECPATH, "build_assets", "app.ico") if os.path.exists(
        os.path.join(SPECPATH, "build_assets", "app.ico")
    ) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="LANVoiceCall",
)
