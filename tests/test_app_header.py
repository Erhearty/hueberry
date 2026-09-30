# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the top app header bar and its use in the main window (offscreen)."""

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QLabel

from hueberry.ui.app_header import BRAND_TEXT, AppHeader
from test_main_window import window  # noqa: F401  (reused fixture)

NAV_TEXT = "&Macros\u2026"
NAV_TIP = "Record macros"


def _index_of(header, widget):
    return header.header_layout().indexOf(widget)


def _stretch_index(header):
    layout = header.header_layout()
    return next(index for index in range(layout.count())
                if layout.itemAt(index).spacerItem() is not None)


def test_object_name_and_brand(qtbot):
    header = AppHeader()
    qtbot.addWidget(header)
    assert header.objectName() == "appHeader"
    assert header.brand_label.text() == BRAND_TEXT
    assert header.brand_label.property("role") == "brand"
    assert _index_of(header, header.brand_label) == 0


def test_add_nav_role_font_and_tip(qtbot):
    header = AppHeader()
    qtbot.addWidget(header)
    button = header.add_nav(NAV_TEXT, NAV_TIP)
    assert button.text() == NAV_TEXT
    assert button.property("role") == "nav"
    assert button.font().capitalization() == QFont.Capitalization.AllUppercase
    assert button.toolTip() == NAV_TIP
    assert _index_of(header, button) < _stretch_index(header)


def test_add_trailing_goes_after_stretch(qtbot):
    header = AppHeader()
    qtbot.addWidget(header)
    nav = header.add_nav(NAV_TEXT, NAV_TIP)
    trailing = QLabel("status")
    header.add_trailing(trailing)
    later_nav = header.add_nav("Other", NAV_TIP)
    stretch = _stretch_index(header)
    assert _index_of(header, nav) < _index_of(header, later_nav) < stretch
    assert _index_of(header, trailing) > stretch


def test_main_window_uses_header(window):  # noqa: F811
    win, _service = window
    assert win.menuWidget() is win.header
    for widget in (win.macros_button, win.daemon_bar):
        assert win.header.isAncestorOf(widget)
