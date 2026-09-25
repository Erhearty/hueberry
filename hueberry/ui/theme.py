# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Dark Fusion theme with a single teal accent colour.

Every colour lives here as a named constant. Text/background pairs meet WCAG AA
(contrast ratio of at least 4.5:1); :func:`contrast_ratio` lets tests check it.
"""

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

STYLE_NAME = "Fusion"

# -- colours -----------------------------------------------------------------
ACCENT = "#26b5a0"          # the one accent colour (teal)
ACCENT_HOVER = "#3cc9b3"    # accent, slightly lighter, for hovered primary buttons
ACCENT_TEXT = "#0d1413"     # text drawn on an accent background
WINDOW = "#1e2124"          # window background
SURFACE = "#2a2e33"         # inputs, cards, tab panes
SURFACE_RAISED = "#33383e"  # buttons, hovered/selected cards
BORDER = "#4a5058"          # outlines of controls (not text)
TEXT = "#e8eaed"            # primary text
TEXT_MUTED = "#a9b0b8"      # secondary text (device type line, hints)
TEXT_DISABLED = "#7c838b"   # disabled controls (exempt from WCAG contrast)
ERROR = "#f28b82"           # error / stopped state
WCAG_AA_MIN_CONTRAST = 4.5

# -- sizes used by the stylesheet (pixels) ------------------------------------
BORDER_PX = 1
FOCUS_BORDER_PX = 2
RADIUS_PX = 4
CARD_RADIUS_PX = 8
BUTTON_PADDING = "5px 12px"
TAB_PADDING = "6px 14px"
CARD_PADDING_PX = 10

# -- WCAG relative luminance (sRGB) -------------------------------------------
CHANNEL_MAX = 255
SRGB_THRESHOLD = 0.03928
SRGB_LINEAR_DIVISOR = 12.92
SRGB_OFFSET = 0.055
SRGB_SCALE = 1.055
SRGB_GAMMA = 2.4
LUMINANCE_WEIGHTS = (0.2126, 0.7152, 0.0722)
CONTRAST_OFFSET = 0.05


def _linear(channel: int) -> float:
    value = channel / CHANNEL_MAX
    if value <= SRGB_THRESHOLD:
        return value / SRGB_LINEAR_DIVISOR
    return ((value + SRGB_OFFSET) / SRGB_SCALE) ** SRGB_GAMMA


def relative_luminance(colour: str) -> float:
    """WCAG relative luminance (0..1) of a ``#rrggbb`` colour."""
    qcolour = QColor(colour)
    channels = (qcolour.red(), qcolour.green(), qcolour.blue())
    return sum(weight * _linear(value) for weight, value in zip(LUMINANCE_WEIGHTS, channels))


def contrast_ratio(first: str, second: str) -> float:
    """WCAG contrast ratio (1..21) between two ``#rrggbb`` colours."""
    lighter, darker = sorted((relative_luminance(first), relative_luminance(second)),
                             reverse=True)
    return (lighter + CONTRAST_OFFSET) / (darker + CONTRAST_OFFSET)


_ROLE_COLOURS = (
    (QPalette.ColorRole.Window, WINDOW),
    (QPalette.ColorRole.WindowText, TEXT),
    (QPalette.ColorRole.Base, SURFACE),
    (QPalette.ColorRole.AlternateBase, SURFACE_RAISED),
    (QPalette.ColorRole.Text, TEXT),
    (QPalette.ColorRole.PlaceholderText, TEXT_MUTED),
    (QPalette.ColorRole.Button, SURFACE_RAISED),
    (QPalette.ColorRole.ButtonText, TEXT),
    (QPalette.ColorRole.BrightText, ERROR),
    (QPalette.ColorRole.Highlight, ACCENT),
    (QPalette.ColorRole.HighlightedText, ACCENT_TEXT),
    (QPalette.ColorRole.Link, ACCENT),
    (QPalette.ColorRole.ToolTipBase, SURFACE_RAISED),
    (QPalette.ColorRole.ToolTipText, TEXT),
)
_DISABLED_ROLES = (
    QPalette.ColorRole.WindowText,
    QPalette.ColorRole.Text,
    QPalette.ColorRole.ButtonText,
)


def build_palette() -> QPalette:
    """Return the dark palette (all colour groups, plus greyed disabled text)."""
    palette = QPalette()
    for role, colour in _ROLE_COLOURS:
        palette.setColor(role, QColor(colour))
    for role in _DISABLED_ROLES:
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(TEXT_DISABLED))
    return palette


STYLESHEET = f"""
QToolTip {{
    color: {TEXT}; background-color: {SURFACE_RAISED};
    border: {BORDER_PX}px solid {BORDER};
}}
QPushButton {{
    color: {TEXT}; background-color: {SURFACE_RAISED};
    border: {BORDER_PX}px solid {BORDER}; border-radius: {RADIUS_PX}px;
    padding: {BUTTON_PADDING};
}}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:focus {{ border: {FOCUS_BORDER_PX}px solid {ACCENT}; }}
QPushButton:disabled {{ color: {TEXT_DISABLED}; border-color: {SURFACE_RAISED}; }}
QPushButton[role="primary"] {{
    color: {ACCENT_TEXT}; background-color: {ACCENT}; border-color: {ACCENT};
}}
QPushButton[role="primary"]:hover {{ background-color: {ACCENT_HOVER}; }}
QPushButton[role="primary"]:focus {{ border: {FOCUS_BORDER_PX}px solid {TEXT}; }}
QPushButton[role="primary"]:disabled {{
    color: {TEXT_DISABLED}; background-color: {SURFACE_RAISED}; border-color: {SURFACE_RAISED};
}}
QTabBar::tab {{
    color: {TEXT_MUTED}; background-color: {SURFACE};
    border: {BORDER_PX}px solid {BORDER}; padding: {TAB_PADDING};
}}
QTabBar::tab:selected {{
    color: {TEXT}; background-color: {SURFACE_RAISED};
    border-bottom: {FOCUS_BORDER_PX}px solid {ACCENT};
}}
QTabBar::tab:hover {{ color: {TEXT}; }}
QStatusBar {{ color: {TEXT}; background-color: {SURFACE}; }}
QScrollArea#deviceGridScroll {{ background-color: transparent; border: none; }}
QToolButton#deviceCard {{
    color: {TEXT}; background-color: {SURFACE};
    border: {BORDER_PX}px solid {BORDER}; border-radius: {CARD_RADIUS_PX}px;
    padding: {CARD_PADDING_PX}px;
}}
QToolButton#deviceCard:hover {{ background-color: {SURFACE_RAISED}; border-color: {ACCENT}; }}
QToolButton#deviceCard:checked {{
    background-color: {SURFACE_RAISED}; border: {FOCUS_BORDER_PX}px solid {ACCENT};
}}
QToolButton#deviceCard:focus {{ border: {FOCUS_BORDER_PX}px solid {TEXT}; }}
"""


def apply_theme(app: QApplication) -> None:
    """Install the Fusion style, the dark palette and the stylesheet on ``app``."""
    app.setStyle(STYLE_NAME)
    app.setPalette(build_palette())
    app.setStyleSheet(STYLESHEET)
