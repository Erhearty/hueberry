# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the macros page section cards (offscreen)."""

import pytest
from PyQt6.QtWidgets import QFrame, QLabel

from hueberry.ui import theme
from hueberry.ui.macros_page import MacrosPage


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
    widget = MacrosPage(None)
    qtbot.addWidget(widget)
    return widget


def test_three_cards_with_headers(page):
    assert sorted(_cards(page)) == ["Devices", "Macro engine", "Macros"]


def test_engine_card_holds_banner_and_start(page):
    card = _cards(page)["Macro engine"]
    assert card.isAncestorOf(page.banner_label)
    assert card.isAncestorOf(page.start_button)


def test_devices_card_holds_device_list(page):
    card = _cards(page)["Devices"]
    assert card.isAncestorOf(page.device_list)
    assert not card.isAncestorOf(page.macro_list)
    assert card.isAncestorOf(page.device_empty_label)


def test_macros_card_holds_list_and_buttons(page):
    card = _cards(page)["Macros"]
    for widget in (page.macro_list, page.add_button, page.edit_button, page.delete_button,
                   page.save_button):
        assert card.isAncestorOf(widget)
    assert not card.isAncestorOf(page.refresh_button)
    assert card.isAncestorOf(page.macro_empty_label)


def test_add_and_save_are_primary(page):
    assert page.add_button.property("role") == "primary"
    assert page.save_button.property("role") == "primary"
