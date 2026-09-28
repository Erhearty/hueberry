# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the dark theme (offscreen)."""

import inspect
import re

import pytest
from PyQt6.QtGui import QFont, QPalette
from PyQt6.QtWidgets import QLabel

from hueberry.ui import theme
from hueberry.ui.colour_button import ColourButton, colour_hex

DARK_LIGHTNESS_MAX = 64
SWATCH = (200, 40, 90)
TEXT_PAIRS = (
    (theme.TEXT, theme.WINDOW),
    (theme.TEXT, theme.SURFACE),
    (theme.TEXT, theme.SURFACE_RAISED),
    (theme.TEXT_MUTED, theme.WINDOW),
    (theme.TEXT_MUTED, theme.SURFACE),
    (theme.TEXT_MUTED, theme.SURFACE_RAISED),
    (theme.ACCENT, theme.WINDOW),
    (theme.ACCENT, theme.SURFACE),
    (theme.ACCENT_TEXT, theme.ACCENT),
    (theme.ACCENT_TEXT, theme.ACCENT_HOVER),
    (theme.ERROR, theme.WINDOW),
    (theme.ERROR, theme.SURFACE),
    (theme.ACCENT, theme.HEADER_BG),
    (theme.TEXT, theme.HEADER_BG),
    (theme.TEXT_MUTED, theme.HEADER_BG),
    (theme.ERROR, theme.HEADER_BG),
    (theme.ACCENT, theme.SURFACE_RAISED),  # chips and badges on a selected list row
    (theme.ERROR, theme.SURFACE_RAISED),
)
HEX_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b")
STYLESHEET_OPEN = 'STYLESHEET = f"""'
STYLESHEET_CLOSE = '"""'
NEW_SELECTORS = (
    'QLabel[role="title"]', 'QLabel[role="error"]', 'QLabel[role="muted"]',
    "QLineEdit", "QComboBox", "QSpinBox", "QListWidget", "QLineEdit:focus",
    "selection-background-color", "QGroupBox", "QGroupBox::title", "QCheckBox:focus",
    "QRadioButton:focus", "QSlider::groove:horizontal", "QSlider::handle:horizontal",
    "QMenu", "QMenu::item:selected",
    "QTabWidget::pane", 'QPushButton[role="nav"]', "QWidget#appHeader",
    'QLabel[role="brand"]', "QSlider::sub-page:horizontal", "QScrollBar:vertical",
    "QFrame#sectionCard", 'QLabel[role="section"]',
    "QWidget#listRow", 'QWidget#listRow[selected="true"]', "QLabel#stateChip",
    'QLabel#stateChip[state="active"]', 'QLabel#stateChip[state="error"]',
    "QLabel#triggerChip", "QLabel#repeatBadge",
)


@pytest.fixture
def themed_app(qapp):
    """Apply the theme, restoring the previous style/palette/stylesheet afterwards."""
    old_style = qapp.style().name()
    old_palette = qapp.palette()
    old_sheet = qapp.styleSheet()
    theme.apply_theme(qapp)
    yield qapp
    qapp.setStyleSheet(old_sheet)
    qapp.setPalette(old_palette)
    if old_style:
        qapp.setStyle(old_style)


def test_fusion_style(themed_app):
    # A stylesheet wraps the style in an unnamed proxy; look underneath it.
    themed_app.setStyleSheet("")
    assert themed_app.style().name().lower() == theme.STYLE_NAME.lower()


def test_stylesheet_installed_with_accent(themed_app):
    assert themed_app.styleSheet() == theme.STYLESHEET
    assert theme.ACCENT in theme.STYLESHEET
    assert '[role="primary"]' in theme.STYLESHEET
    for selector in ("#deviceCard:hover", "#deviceCard:focus", "#deviceCard:checked"):
        assert selector in theme.STYLESHEET


def test_window_colour_is_dark(themed_app):
    window = themed_app.palette().color(QPalette.ColorRole.Window)
    assert window.lightness() < DARK_LIGHTNESS_MAX
    assert window.name() == theme.WINDOW


def test_accent_is_not_the_vendor_green():
    assert theme.ACCENT.lower() != "#44d62c"


def test_accent_is_aqua():
    assert theme.ACCENT.lower() == "#18ebcd"


def test_stylesheet_has_no_hex_literal():
    # STYLESHEET is an f-string: check its source template, where colours must be tokens.
    source = inspect.getsource(theme)
    start = source.index(STYLESHEET_OPEN) + len(STYLESHEET_OPEN)
    template = source[start:source.index(STYLESHEET_CLOSE, start)]
    assert "{ACCENT}" in template
    assert HEX_LITERAL.search(template) is None


def test_uppercase_sets_all_uppercase(qtbot):
    label = QLabel("Title")
    qtbot.addWidget(label)
    theme.uppercase(label)
    assert label.font().capitalization() == QFont.Capitalization.AllUppercase
    assert label.font().letterSpacing() == theme.LETTER_SPACING_PCT
    assert label.text() == "Title"


@pytest.mark.parametrize(("foreground", "background"), TEXT_PAIRS)
def test_text_pairs_meet_wcag_aa(foreground, background):
    assert theme.contrast_ratio(foreground, background) >= theme.WCAG_AA_MIN_CONTRAST


@pytest.mark.parametrize("selector", NEW_SELECTORS)
def test_stylesheet_has_polish_selectors(selector):
    assert selector in theme.STYLESHEET


def test_title_role_uses_font_token():
    assert f"font-size: {theme.TITLE_FONT_PT}pt" in theme.STYLESHEET


def test_set_role_sets_property(qtbot):
    label = QLabel("x")
    qtbot.addWidget(label)
    theme.set_role(label, "error")
    assert label.property("role") == "error"
    theme.set_role(label, "muted")
    assert label.property("role") == "muted"


def test_set_role_repolishes_shown_widget(qtbot):
    label = QLabel("x")
    label.setStyleSheet(theme.STYLESHEET)
    qtbot.addWidget(label)
    theme.set_role(label, "error")
    label.show()
    assert label.palette().color(QPalette.ColorRole.WindowText).name() == theme.ERROR.lower()
    theme.set_role(label, "muted")
    assert label.palette().color(QPalette.ColorRole.WindowText).name() == theme.TEXT_MUTED.lower()


def test_colour_button_keeps_swatch_after_theme(themed_app, qtbot):
    button = ColourButton("Colour", SWATCH)
    qtbot.addWidget(button)
    assert colour_hex(SWATCH) in button.styleSheet()
