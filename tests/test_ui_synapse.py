# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the Synapse-style device page tabs and empty-state title (offscreen)."""

import pytest
from PyQt6.QtGui import QFont

from hueberry.ui.device_page import TAB_INFO, TAB_LIGHTING, TAB_PERFORMANCE, DevicePage
from hueberry.ui.empty_state import EmptyStatePanel


@pytest.fixture
def page(qtbot):
    widget = DevicePage()
    qtbot.addWidget(widget)
    return widget


def test_tabs_use_document_mode(page):
    assert page.tabs.documentMode() is True


def test_tab_bar_font_is_uppercase(page):
    assert page.tabs.tabBar().font().capitalization() == QFont.Capitalization.AllUppercase


def test_tab_text_is_unchanged(page):
    texts = [page.tabs.tabText(index) for index in range(page.tabs.count())]
    assert texts == [TAB_LIGHTING, TAB_PERFORMANCE, TAB_INFO]


def test_empty_state_title_is_uppercase(qtbot):
    panel = EmptyStatePanel()
    qtbot.addWidget(panel)
    assert panel.title_label.font().capitalization() == QFont.Capitalization.AllUppercase
