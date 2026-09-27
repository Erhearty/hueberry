# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Synapse-style near-black Fusion theme with a single aqua accent colour.

Every colour lives here as a named constant. Text/background pairs meet WCAG AA
(contrast ratio of at least 4.5:1); :func:`contrast_ratio` lets tests check it.
"""

from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import QApplication, QWidget

STYLE_NAME = "Fusion"

# -- colours -----------------------------------------------------------------
ACCENT = "#18ebcd"          # the one accent colour (aqua accent)
ACCENT_HOVER = "#5ff2de"    # accent, slightly lighter, for hovered primary buttons
ACCENT_TEXT = "#0a0a0a"     # text drawn on an accent background
WINDOW = "#0f0f10"          # window background
SURFACE = "#18181a"         # inputs, cards, tab panes
SURFACE_RAISED = "#222225"  # buttons, hovered/selected cards
BORDER = "#34343a"          # outlines of controls (not text)
TEXT = "#ececec"            # primary text
TEXT_MUTED = "#9c9ca3"      # secondary text (device type line, hints)
TEXT_DISABLED = "#66666c"   # disabled controls (exempt from WCAG contrast)
ERROR = "#f28b82"           # error / stopped state
HEADER_BG = "#000000"       # top app header bar
WCAG_AA_MIN_CONTRAST = 4.5

# -- sizes used by the stylesheet (pixels) ------------------------------------
BORDER_PX = 1
FOCUS_BORDER_PX = 2
RADIUS_PX = 2
CARD_RADIUS_PX = 4
BUTTON_PADDING = "5px 12px"
TAB_PADDING = "6px 14px"
CARD_PADDING_PX = 10
SLIDER_GROOVE_PX = 4
SLIDER_HANDLE_PX = 14
SLIDER_HANDLE_MARGIN_PX = (SLIDER_HANDLE_PX - SLIDER_GROOVE_PX) // 2  # handle overhang
SLIDER_HANDLE_RADIUS_PX = SLIDER_HANDLE_PX // 2  # round slider handle
TAB_INDICATOR_PX = 3  # accent underline of the selected tab / nav button
SCROLLBAR_WIDTH_PX = 8  # thin vertical scroll bar

# -- layout spacing (pixels) and fonts ------------------------------------------
SPACING_S = 6         # between buttons in a row, between form rows
SPACING_M = 12        # between page sections, form label/field gap
PAGE_MARGIN_PX = 16   # outer margin of each page
TITLE_FONT_PT = 14    # page / empty-state titles
LETTER_SPACING_PCT = 108  # letter spacing of uppercase labels (percent)

# -- object names styled by the stylesheet --------------------------------------
SECTION_OBJECT_NAME = "sectionCard"  # QFrame of a settings section card

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
    font-weight: bold;
}}
QPushButton[role="primary"]:hover {{ background-color: {ACCENT_HOVER}; }}
QPushButton[role="primary"]:focus {{ border: {FOCUS_BORDER_PX}px solid {TEXT}; }}
QPushButton[role="primary"]:disabled {{
    color: {TEXT_DISABLED}; background-color: {SURFACE_RAISED}; border-color: {SURFACE_RAISED};
}}
QPushButton[role="nav"] {{
    color: {TEXT_MUTED}; background-color: transparent;
    border: {FOCUS_BORDER_PX}px solid transparent;
    font-weight: bold; padding: {BUTTON_PADDING};
}}
QPushButton[role="nav"]:hover {{ color: {TEXT}; }}
QPushButton[role="nav"]:checked {{
    color: {TEXT}; border-bottom: {TAB_INDICATOR_PX}px solid {ACCENT};
}}
QPushButton[role="nav"]:focus {{ border: {FOCUS_BORDER_PX}px solid {ACCENT}; }}
QTabWidget::pane {{ border: none; border-top: {BORDER_PX}px solid {BORDER}; }}
QTabBar::tab {{
    color: {TEXT_MUTED}; background-color: transparent; border: none;
    border-bottom: {TAB_INDICATOR_PX}px solid transparent;
    font-weight: bold; padding: {TAB_PADDING};
}}
QTabBar::tab:selected {{
    color: {TEXT}; border-bottom: {TAB_INDICATOR_PX}px solid {ACCENT};
}}
QTabBar::tab:hover {{ color: {TEXT}; }}
QWidget#appHeader {{
    background-color: {HEADER_BG}; border-bottom: {BORDER_PX}px solid {BORDER};
}}
QLabel[role="brand"] {{ color: {ACCENT}; font-weight: bold; font-size: {TITLE_FONT_PT}pt; }}
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
QLabel[role="title"] {{ font-size: {TITLE_FONT_PT}pt; font-weight: bold; }}
QLabel[role="error"] {{ color: {ERROR}; }}
QLabel[role="muted"] {{ color: {TEXT_MUTED}; }}
QFrame#{SECTION_OBJECT_NAME} {{
    background-color: {SURFACE};
    border: {BORDER_PX}px solid {BORDER}; border-radius: {CARD_RADIUS_PX}px;
}}
QLabel[role="section"] {{ color: {TEXT_MUTED}; font-weight: bold; }}
QLineEdit, QComboBox, QSpinBox, QListWidget {{
    background-color: {SURFACE};
    border: {BORDER_PX}px solid {BORDER}; border-radius: {RADIUS_PX}px;
    selection-background-color: {ACCENT}; selection-color: {ACCENT_TEXT};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QListWidget:focus {{
    border: {FOCUS_BORDER_PX}px solid {ACCENT};
}}
QGroupBox {{
    border: {BORDER_PX}px solid {BORDER}; border-radius: {RADIUS_PX}px;
    margin-top: {SPACING_M}px; padding-top: {SPACING_S}px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left;
    left: {SPACING_M}px; padding: 0 {SPACING_S}px; color: {TEXT};
}}
QCheckBox:focus, QRadioButton:focus {{ color: {ACCENT}; }}
QSlider::groove:horizontal {{
    height: {SLIDER_GROOVE_PX}px; background-color: {SURFACE_RAISED};
    border-radius: {RADIUS_PX}px;
}}
QSlider::sub-page:horizontal {{
    background-color: {ACCENT}; border-radius: {RADIUS_PX}px;
}}
QSlider::handle:horizontal {{
    width: {SLIDER_HANDLE_PX}px; background-color: {TEXT};
    margin: -{SLIDER_HANDLE_MARGIN_PX}px 0; border-radius: {SLIDER_HANDLE_RADIUS_PX}px;
}}
QSlider::handle:horizontal:focus {{ border: {FOCUS_BORDER_PX}px solid {ACCENT}; }}
QSlider::sub-page:horizontal:disabled {{ background-color: {BORDER}; }}
QSlider::handle:horizontal:disabled {{ background-color: {TEXT_DISABLED}; }}
QMenu {{
    color: {TEXT}; background-color: {SURFACE_RAISED};
    border: {BORDER_PX}px solid {BORDER};
}}
QMenu::item:selected {{ color: {ACCENT_TEXT}; background-color: {ACCENT}; }}
QScrollBar:vertical {{
    width: {SCROLLBAR_WIDTH_PX}px; background-color: {SURFACE}; border: none;
}}
QScrollBar::handle:vertical {{ background-color: {BORDER}; border-radius: {RADIUS_PX}px; }}
QScrollBar::handle:vertical:hover {{ background-color: {ACCENT}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
"""


def set_role(widget: QWidget, role: str) -> None:
    """Give ``widget`` the stylesheet ``role`` property and re-polish it so it takes effect."""
    widget.setProperty("role", role)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def uppercase(widget: QWidget) -> None:
    """Render ``widget``'s text in capitals with wider letter spacing (the text is unchanged)."""
    font = widget.font()
    font.setCapitalization(QFont.Capitalization.AllUppercase)
    font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, LETTER_SPACING_PCT)
    widget.setFont(font)


def apply_theme(app: QApplication) -> None:
    """Install the Fusion style, the dark palette and the stylesheet on ``app``."""
    app.setStyle(STYLE_NAME)
    app.setPalette(build_palette())
    app.setStyleSheet(STYLESHEET)
