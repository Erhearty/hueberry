# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the presets page section cards (offscreen)."""

import pytest
from PyQt6.QtWidgets import QFrame, QGroupBox, QLabel

from hueberry.ui import theme
from hueberry.ui.presets_page import PresetsPage


def _cards(widget):
    """Section cards under ``widget``, keyed by their header text."""
    cards = {}
    for frame in widget.findChildren(QFrame):
        if frame.objectName() == theme.SECTION_OBJECT_NAME:
            header = frame.layout().itemAt(0).widget()
            assert isinstance(header, QLabel)
            cards[header.text()] = frame
    return cards


@pytest.fixture
def page(qtbot):
    widget = PresetsPage()
    qtbot.addWidget(widget)
    return widget


def test_three_cards_with_headers(page):
    assert sorted(_cards(page)) == ["Apply to devices", "Editor", "Presets"]


def test_no_group_box_left(page):
    assert page.findChildren(QGroupBox) == []


def test_presets_card_holds_list_and_buttons(page):
    card = _cards(page)["Presets"]
    for widget in (page.preset_list, page.new_button, page.duplicate_button,
                   page.delete_button, page.save_button):
        assert card.isAncestorOf(widget)
    assert not card.isAncestorOf(page.device_list)


def test_editor_card_holds_editor(page):
    assert _cards(page)["Editor"].isAncestorOf(page.editor)


def test_apply_card_holds_devices_and_actions(page):
    card = _cards(page)["Apply to devices"]
    for widget in (page.device_list, page.single_radio, page.group_radio, page.stop_button,
                   page.apply_button):
        assert card.isAncestorOf(widget)
    assert not card.isAncestorOf(page.preset_list)
