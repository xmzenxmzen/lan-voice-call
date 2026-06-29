"""Bootstrap patch: ensure opus.dll is loadable on Windows.

When the app is frozen by PyInstaller, `ctypes.util.find_library('opus')`
fails because opus.dll is not on the system PATH. We pre-load it from the
exe directory before opuslib tries to use it.

This module must be imported BEFORE opuslib is imported anywhere.
"""
import os
import sys


def preload_opus() -> None:
    if sys.platform != "win32":
        return
    # Find candidate DLL locations
    candidates = []
    if getattr(sys, "frozen", False):
        # PyInstaller bundle: DLL is in _internal/ (PyInstaller 6+) or next to exe
        base = os.path.dirname(sys.executable)
        candidates.append(os.path.join(base, "opus.dll"))
        candidates.append(os.path.join(base, "libopus-0.dll"))
        candidates.append(os.path.join(base, "_internal", "opus.dll"))
        candidates.append(os.path.join(base, "_internal", "libopus-0.dll"))
    # Also check this script's directory (dev mode)
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(here, "opus.dll"))
    candidates.append(os.path.join(here, "dll", "opus.dll"))
    candidates.append(os.path.join(here, "libopus-0.dll"))

    # If ctypes can already find it via find_library, skip pre-loading.
    try:
        import ctypes.util
        if ctypes.util.find_library("opus") or ctypes.util.find_library("libopus-0"):
            return
    except Exception:
        pass

    # Try to load any candidate that exists.
    import ctypes
    for path in candidates:
        if os.path.isfile(path):
            try:
                # Preload with full path - opuslib will then find it by name.
                ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL if hasattr(ctypes, "RTLD_GLOBAL") else 0)
                # Also add the directory to PATH so find_library can locate it.
                os.environ["PATH"] = os.path.dirname(path) + os.pathsep + os.environ.get("PATH", "")
                return
            except OSError:
                continue

    # If none worked, opuslib will fall back to PCM at runtime.


# Run on import.
preload_opus()
