"""LAN Voice Call - standalone entry script (no relative imports).

This file is what PyInstaller packages as the entry point. It bootstraps
the package import path and calls `lan_voice_call.main.main()`.

Kept separate from lan_voice_call/main.py so that:
  1. PyInstaller can use it as the script target without relative-import
     issues.
  2. `python -m lan_voice_call` still works for development.
"""
import sys
import os


def _bootstrap() -> None:
    # If running from a PyInstaller bundle, _internal/ holds the packages.
    # PyInstaller already adds the right path, but we double-check.
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)


def main() -> int:
    _bootstrap()
    from lan_voice_call.main import main as _real_main
    return _real_main()


if __name__ == "__main__":
    sys.exit(main())
