"""Modern dark theme (Discord/Telegram-inspired) for LAN Voice Call."""

# Color palette
BG_DEEPEST = "#0f1117"     # window background
BG_PANEL = "#1a1d27"       # side panels
BG_CARD = "#222632"        # list items / cards
BG_CARD_HOVER = "#2a2f3d"
BG_INPUT = "#1f2230"

TEXT_PRIMARY = "#e8eaf0"
TEXT_SECONDARY = "#9aa3b2"
TEXT_MUTED = "#6b7280"

ACCENT = "#14b8a6"         # teal
ACCENT_HOVER = "#0d9488"
ACCENT_PRESSED = "#0f766e"

DANGER = "#ef4444"
DANGER_HOVER = "#dc2626"
SUCCESS = "#22c55e"
WARNING = "#f59e0b"

BORDER = "#2a2f3d"
BORDER_LIGHT = "#3a3f4d"


QSS = f"""
QWidget {{
    background-color: {BG_DEEPEST};
    color: {TEXT_PRIMARY};
    font-family: "Segoe UI", "Roboto", "SF Pro Display", "Arial", sans-serif;
    font-size: 13px;
}}

/* ---------- Window ---------- */
QMainWindow, QDialog {{
    background-color: {BG_DEEPEST};
}}

/* ---------- Panels ---------- */
QFrame#leftPanel, QFrame#rightPanel {{
    background-color: {BG_PANEL};
    border: none;
}}

QFrame#headerBar {{
    background-color: {BG_PANEL};
    border-bottom: 1px solid {BORDER};
}}

QLabel#headerTitle {{
    color: {TEXT_PRIMARY};
    font-size: 16px;
    font-weight: 600;
}}

QLabel#sectionTitle {{
    color: {TEXT_SECONDARY};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
    text-transform: uppercase;
}}

QLabel#statusLabel {{
    color: {TEXT_SECONDARY};
    font-size: 12px;
}}

QLabel#bigLabel {{
    color: {TEXT_PRIMARY};
    font-size: 18px;
    font-weight: 600;
}}

QLabel#smallMuted {{
    color: {TEXT_MUTED};
    font-size: 11px;
}}

/* ---------- Username field ---------- */
QLineEdit {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 10px;
    color: {TEXT_PRIMARY};
    selection-background-color: {ACCENT};
}}
QLineEdit:focus {{
    border: 1px solid {ACCENT};
}}

/* ---------- Buttons ---------- */
QPushButton {{
    background-color: {BG_CARD};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 7px 14px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {BG_CARD_HOVER};
    border: 1px solid {BORDER_LIGHT};
}}
QPushButton:pressed {{
    background-color: {BG_INPUT};
}}
QPushButton:disabled {{
    color: {TEXT_MUTED};
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
}}

QPushButton#primaryBtn {{
    background-color: {ACCENT};
    color: white;
    border: 1px solid {ACCENT};
}}
QPushButton#primaryBtn:hover {{
    background-color: {ACCENT_HOVER};
    border: 1px solid {ACCENT_HOVER};
}}
QPushButton#primaryBtn:pressed {{
    background-color: {ACCENT_PRESSED};
}}
QPushButton#primaryBtn:disabled {{
    background-color: {BG_INPUT};
    color: {TEXT_MUTED};
    border: 1px solid {BORDER};
}}

QPushButton#dangerBtn {{
    background-color: {DANGER};
    color: white;
    border: 1px solid {DANGER};
}}
QPushButton#dangerBtn:hover {{
    background-color: {DANGER_HOVER};
    border: 1px solid {DANGER_HOVER};
}}
QPushButton#dangerBtn:disabled {{
    background-color: {BG_INPUT};
    color: {TEXT_MUTED};
    border: 1px solid {BORDER};
}}

QPushButton#successBtn {{
    background-color: {SUCCESS};
    color: white;
    border: 1px solid {SUCCESS};
}}
QPushButton#successBtn:hover {{
    background-color: #16a34a;
}}

QPushButton#ghostBtn {{
    background-color: transparent;
    border: 1px solid {BORDER_LIGHT};
}}
QPushButton#ghostBtn:hover {{
    background-color: {BG_CARD};
}}

/* ---------- List widgets ---------- */
QListWidget {{
    background-color: transparent;
    border: none;
    outline: none;
}}
QListWidget::item {{
    border-bottom: 1px solid {BORDER};
    padding: 0;
}}
QListWidget::item:selected {{
    background-color: {BG_CARD};
}}

/* ---------- Scroll bar ---------- */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER_LIGHT};
    min-height: 30px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical:hover {{
    background: {TEXT_MUTED};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER_LIGHT};
    min-width: 30px;
    border-radius: 4px;
}}

/* ---------- Slider ---------- */
QSlider::groove:horizontal {{
    height: 4px;
    background: {BORDER};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: white;
    width: 14px;
    height: 14px;
    margin: -6px 0;
    border-radius: 7px;
}}
QSlider::handle:horizontal:hover {{
    background: {ACCENT};
}}

/* ---------- Status dot ---------- */
QLabel#dotIdle {{ color: {TEXT_MUTED}; }}
QLabel#dotCalling {{ color: {WARNING}; }}
QLabel#dotIncoming {{ color: {WARNING}; }}
QLabel#dotInCall {{ color: {SUCCESS}; }}

/* ---------- Level meter ---------- */
QProgressBar {{
    background-color: {BG_INPUT};
    border: none;
    border-radius: 2px;
    text-align: center;
    height: 4px;
}}
QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 2px;
}}

/* ---------- ScrollArea ---------- */
QScrollArea {{
    background-color: transparent;
    border: none;
}}
QScrollArea > QWidget > QWidget {{
    background-color: transparent;
}}

/* ---------- Tooltip ---------- */
QToolTip {{
    background-color: {BG_CARD};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_LIGHT};
    border-radius: 4px;
    padding: 4px 8px;
}}
"""


def apply_theme(app) -> None:
    """Apply the dark theme to a QApplication."""
    app.setStyleSheet(QSS)
