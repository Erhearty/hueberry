# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the device card grid (offscreen)."""

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget

from hueberry.backend.devices import DeviceInfo
from hueberry.ui import device_cards
from hueberry.ui.device_cards import DeviceGrid, columns_for_width

WIDE = 2000
NARROW = 100
HEIGHT = 400


def _info(name, device_type, serial):
    return DeviceInfo(name=name, type=device_type, serial=serial, firmware_version="v1",
                      driver_version="1", has_matrix=False, is_mouse=device_type == "mouse")


INFOS = [
    _info("Test Mouse", "mouse", "M1"),
    _info("Test Keyboard", "keyboard", "K1"),
    _info("Test Headset", "headset", "H1"),
]


@pytest.fixture
def grid(qtbot):
    widget = DeviceGrid()
    qtbot.addWidget(widget)
    widget.set_devices(INFOS)
    return widget


def test_cards_created(grid):
    assert grid.count() == len(INFOS)
    card = grid.cards()[0]
    assert card.objectName() == "deviceCard"
    assert card.text() == "Test Mouse\nmouse"
    assert card.toolTip() == "M1"
    assert card.accessibleDescription() == "M1"
    assert card.property("serial") == "M1"
    assert card.isCheckable()
    assert card.focusPolicy() & Qt.FocusPolicy.TabFocus
    assert not card.icon().isNull()
    assert grid.selected_serial() is None


def test_select_serial_is_exclusive(grid):
    assert grid.select_serial("K1")
    assert grid.selected_serial() == "K1"
    assert grid.select_serial("H1")
    assert grid.selected_serial() == "H1"
    assert [card.isChecked() for card in grid.cards()] == [False, False, True]
    assert not grid.select_serial("missing")
    assert grid.selected_serial() == "H1"


def test_click_activates(grid, qtbot):
    with qtbot.waitSignal(grid.device_activated) as blocker:
        grid.cards()[1].click()
    assert blocker.args == ["K1"]
    assert grid.selected_serial() == "K1"


@pytest.mark.parametrize("key", [Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter])
def test_keyboard_activates(grid, qtbot, key):
    card = grid.cards()[2]
    with qtbot.waitSignal(grid.device_activated) as blocker:
        qtbot.keyClick(card, key)
    assert blocker.args == ["H1"]


@pytest.mark.parametrize(("width", "start", "key", "expected"), [
    (WIDE, 0, Qt.Key.Key_Right, 1),
    (WIDE, 1, Qt.Key.Key_Left, 0),
    (NARROW, 0, Qt.Key.Key_Down, 1),
    (NARROW, 1, Qt.Key.Key_Up, 0),
])
def test_arrow_keys_move_focus_without_activating(qtbot, width, start, key, expected):
    parent = QWidget()
    qtbot.addWidget(parent)
    grid = DeviceGrid(parent)
    grid.set_devices(INFOS)
    parent.show()
    qtbot.waitExposed(parent)
    grid.resize(width, HEIGHT)
    cards = grid.cards()
    grid.select_serial(cards[start].serial)  # a checked card is what made Qt click the neighbour
    cards[start].setFocus()
    with qtbot.assertNotEmitted(grid.device_activated):
        qtbot.keyClick(cards[start], key)
    assert parent.focusWidget() is cards[expected]
    assert grid.selected_serial() == cards[start].serial


def test_set_devices_keeps_selection(grid):
    grid.select_serial("K1")
    grid.set_devices(list(reversed(INFOS)))
    assert grid.count() == len(INFOS)
    assert grid.cards()[0].serial == "H1"
    assert grid.selected_serial() == "K1"
    grid.set_devices(INFOS[:1])
    assert grid.count() == 1
    assert grid.selected_serial() is None


def test_columns_for_width():
    assert columns_for_width(NARROW) == device_cards.MIN_COLUMNS
    assert columns_for_width(WIDE * WIDE) == device_cards.MAX_COLUMNS
    two = 2 * device_cards.CARD_WIDTH + device_cards.GRID_SPACING
    assert columns_for_width(two) == 2
    assert columns_for_width(two - 1) == 1


def _position(grid, card):
    row, column, _rows, _columns = grid.grid_layout.getItemPosition(
        grid.grid_layout.indexOf(card))
    return row, column


def test_grid_reflows_with_width(qtbot):
    # A child of a shown parent resizes synchronously (no window manager involved).
    parent = QWidget()
    qtbot.addWidget(parent)
    grid = DeviceGrid(parent)
    grid.set_devices(INFOS)
    parent.show()
    grid.resize(WIDE, HEIGHT)
    assert grid.columns() == device_cards.MAX_COLUMNS
    assert _position(grid, grid.cards()[2]) == (0, 2)
    grid.resize(NARROW, HEIGHT)
    assert grid.columns() == device_cards.MIN_COLUMNS
    assert _position(grid, grid.cards()[2]) == (2, 0)
