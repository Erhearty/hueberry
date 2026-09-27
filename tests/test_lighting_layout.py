# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the lighting panel's Effect / Brightness section cards (offscreen)."""

import pytest
from PyQt6.QtWidgets import QFrame, QLabel

from hueberry.backend.lighting import PARAM_COLOUR2
from hueberry.ui import theme
from hueberry.ui.lighting_panel import LightingPanel

LIGHTING_CAPS = ("lighting", "lighting_static", "lighting_breath_dual")


def _cards(widget):
    """Section cards under ``widget``, in creation order."""
    return [frame for frame in widget.findChildren(QFrame)
            if frame.objectName() == theme.SECTION_OBJECT_NAME]


def _header_text(card):
    header = card.layout().itemAt(0).widget()
    assert isinstance(header, QLabel)
    return header.text()


def _select_effect(panel, key):
    index = panel.effect_combo.findData(key)
    assert index >= 0, key
    panel.effect_combo.setCurrentIndex(index)


@pytest.fixture
def panel(qtbot):
    widget = LightingPanel()
    qtbot.addWidget(widget)
    return widget


def test_two_cards_with_headers(panel):
    assert [_header_text(card) for card in _cards(panel)] == ["Effect", "Brightness"]


def test_widgets_sit_in_their_cards(panel):
    effect_card, brightness_card = _cards(panel)
    assert brightness_card.isAncestorOf(panel.brightness_slider)
    assert not effect_card.isAncestorOf(panel.brightness_slider)
    for widget in (panel.effect_combo, panel.colour1_button, panel.colour2_button,
                   panel.speed_combo):
        assert effect_card.isAncestorOf(widget)
    assert not any(card.isAncestorOf(panel.apply_button) for card in (effect_card,
                                                                      brightness_card))


def test_param_rows_toggle_per_effect(panel, make_device):
    panel.set_device(make_device(device_type="keyboard", capabilities=LIGHTING_CAPS))
    _select_effect(panel, "static")
    assert panel.colour1_button.isVisibleTo(panel)
    assert not panel.colour2_button.isVisibleTo(panel)
    assert not panel._labels[PARAM_COLOUR2].isVisibleTo(panel)
    _select_effect(panel, "breath_dual")
    assert panel.colour2_button.isVisibleTo(panel)
    assert panel._labels[PARAM_COLOUR2].isVisibleTo(panel)
