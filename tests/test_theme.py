# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the dark theme (offscreen)."""

import pytest
from PyQt6.QtGui import QPalette

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


@pytest.mark.parametrize(("foreground", "background"), TEXT_PAIRS)
def test_text_pairs_meet_wcag_aa(foreground, background):
    assert theme.contrast_ratio(foreground, background) >= theme.WCAG_AA_MIN_CONTRAST


def test_colour_button_keeps_swatch_after_theme(themed_app, qtbot):
    button = ColourButton("Colour", SWATCH)
    qtbot.addWidget(button)
    assert colour_hex(SWATCH) in button.styleSheet()
