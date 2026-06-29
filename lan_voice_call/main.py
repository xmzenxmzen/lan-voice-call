"""LAN Voice Call - application entry point.

Use `python -m lan_voice_call` or call `lan_voice_call.main.main()` from
a launcher script (e.g. run.py for PyInstaller builds).
"""
from __future__ import annotations

import sys
import os
import traceback

# Preload opus.dll on Windows BEFORE any opuslib import.
try:
    from . import _opus_loader  # noqa: F401  (relative import is OK here)
except ImportError:
    # Running as a top-level script (e.g. python lan_voice_call/main.py)
    # In that case the package isn't initialized; skip the preload.
    pass

# Ensure high-DPI scaling doesn't break.
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")


def main() -> int:
    try:
        from PyQt5.QtCore import Qt
        # High-DPI awareness (Qt5 way).
        try:
            from PyQt5.QtWidgets import QApplication
            QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
            QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        except Exception:
            pass

        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtCore import QTimer
        from .ui import MainWindow, apply_theme
        from . import config

        app = QApplication(sys.argv)
        app.setApplicationName(config.APP_NAME)
        app.setApplicationVersion(config.APP_VERSION)
        app.setOrganizationName("LANVoiceCall")
        app.setWindowIcon(_default_icon())
        apply_theme(app)

        window = MainWindow()
        window.show()

        # Optional auto-quit (used by the verify_binary test script).
        quit_after = os.environ.get("LAN_VOICE_CALL_QUIT_AFTER_MS")
        if quit_after:
            try:
                ms = int(quit_after)
                QTimer.singleShot(ms, app.quit)
            except ValueError:
                pass

        return app.exec_()
    except Exception:
        traceback.print_exc()
        # Try to show a message box if Qt is partially up.
        try:
            from PyQt5.QtWidgets import QMessageBox, QApplication
            if QApplication.instance():
                QMessageBox.critical(
                    None, "LAN Voice Call - Fatal error",
                    traceback.format_exc()
                )
        except Exception:
            pass
        return 1


def _default_icon():
    """A simple teal microphone icon (QIcon built from a generated pixmap)."""
    try:
        from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor, QBrush, QPen
        from PyQt5.QtCore import Qt, QRect
        pix = QPixmap(64, 64)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QBrush(QColor("#14b8a6")))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(0, 0, 64, 64, 14, 14)
        # Mic body
        p.setBrush(QBrush(QColor("white")))
        p.drawRoundedRect(QRect(26, 14, 12, 26), 6, 6)
        p.setPen(QPen(QColor("white"), 3))
        p.drawArc(QRect(20, 24, 24, 24), 0, -180 * 16)
        p.drawLine(32, 44, 32, 50)
        p.drawLine(24, 50, 40, 50)
        p.end()
        return QIcon(pix)
    except Exception:
        return QIcon()


if __name__ == "__main__":
    sys.exit(main())
