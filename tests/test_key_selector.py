# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""qtbot tests for the key selector: every mouse gesture and the keyboard."""

import pytest
from PyQt6.QtCore import QByteArray, QEvent, QPoint, QPointF, QRectF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QApplication

from hueberry.backend import device_maps
from hueberry.ui.device_graphic import DeviceGraphic
from hueberry.ui.key_selector import KeySelector

ROWS = 6
COLS = 22
WIDTH = 448
HEIGHT = 128
CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier
LEFT = Qt.MouseButton.LeftButton
KEYBOARD_MAP = "blackwidow_elite_en_US.svg"
KEYBOARD_SIZE = (944, 373)
KEYBOARD_KEYS = ((0, 1), (0, 14))  # Esc (x1-y0) and F12 (x14-y0)
MOUSE_MAP = "basilisk_v3.svg"
MOUSE_SIZE = (300, 400)
EDGE = 4.0  # the selector's margin, restated so the expected geometry is independent
CORNER = QPoint(1, 1)  # inside the margin: never on a key
HALF = 0.5


@pytest.fixture
def selector(qtbot):
    widget = KeySelector(ROWS, COLS, name="Keyboard")
    qtbot.addWidget(widget)
    widget.resize(WIDTH, HEIGHT)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def _centre(widget, cell):
    return widget.cell_rect(*cell).center().toPoint()


def _click(qtbot, widget, cell, mods=Qt.KeyboardModifier.NoModifier):
    qtbot.mouseClick(widget, LEFT, mods, _centre(widget, cell))


def test_accessible_and_focusable(selector):
    assert selector.accessibleName() == "Key selector: Keyboard"
    assert selector.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert "0 of 132 keys selected" in selector.accessibleDescription()


def test_click_selects_one_and_emits(qtbot, selector):
    with qtbot.waitSignal(selector.selection_changed) as blocker:
        _click(qtbot, selector, (2, 3))
    assert blocker.args == [frozenset({(2, 3)})]
    _click(qtbot, selector, (3, 4))
    assert selector.selection() == {(3, 4)}


def test_ctrl_click_toggles(qtbot, selector):
    _click(qtbot, selector, (2, 3))
    _click(qtbot, selector, (3, 4), CTRL)
    assert selector.selection() == {(2, 3), (3, 4)}
    _click(qtbot, selector, (2, 3), CTRL)
    assert selector.selection() == {(3, 4)}


def test_shift_click_rectangle(qtbot, selector):
    _click(qtbot, selector, (1, 1))
    _click(qtbot, selector, (2, 3), SHIFT)
    assert selector.selection() == {(r, c) for r in (1, 2) for c in (1, 2, 3)}


def _move(widget, point, mods):
    """Send a mouse move with the left button held (qtbot.mouseMove cannot)."""
    event = QMouseEvent(QEvent.Type.MouseMove, QPointF(point),
                        QPointF(widget.mapToGlobal(point)), LEFT, LEFT, mods)
    QApplication.sendEvent(widget, event)


def _drag(qtbot, widget, start, end, mods=Qt.KeyboardModifier.NoModifier):
    first, last = _centre(widget, start), _centre(widget, end)
    qtbot.mousePress(widget, LEFT, mods, first)
    _move(widget, first + QPoint(1, 1), mods)  # below the drag threshold
    _move(widget, last, mods)
    qtbot.mouseRelease(widget, LEFT, mods, last)


def test_drag_rubber_band(qtbot, selector):
    _drag(qtbot, selector, (0, 0), (1, 2))
    assert selector.selection() == {(r, c) for r in (0, 1) for c in (0, 1, 2)}


def test_ctrl_drag_adds(qtbot, selector):
    _click(qtbot, selector, (5, 21))
    _drag(qtbot, selector, (0, 0), (0, 1), CTRL)
    assert selector.selection() == {(5, 21), (0, 0), (0, 1)}


def test_keyboard_navigation(qtbot, selector):
    selector.setFocus()
    assert selector.cursor() == (0, 0)
    qtbot.keyClick(selector, Qt.Key.Key_Right)
    qtbot.keyClick(selector, Qt.Key.Key_Down)
    assert selector.cursor() == (1, 1)
    qtbot.keyClick(selector, Qt.Key.Key_Space)
    assert selector.selection() == {(1, 1)}
    qtbot.keyClick(selector, Qt.Key.Key_Right, SHIFT)
    assert selector.selection() == {(1, 1), (1, 2)}
    qtbot.keyClick(selector, Qt.Key.Key_Space)
    assert selector.selection() == {(1, 1)}
    qtbot.keyClick(selector, Qt.Key.Key_A, CTRL)
    assert len(selector.selection()) == ROWS * COLS
    qtbot.keyClick(selector, Qt.Key.Key_Escape)
    assert selector.selection() == frozenset()
    qtbot.keyClick(selector, Qt.Key.Key_Up)
    qtbot.keyClick(selector, Qt.Key.Key_Up)
    assert selector.cursor() == (0, 2)
    assert "focused key row 1, column 3" in selector.accessibleDescription()


def _packaged(filename):
    """The index entry and SVG bytes of a packaged map, or skip."""
    for device_map in device_maps.load_index().values():
        if device_map.filename == filename:
            data = device_maps.svg_bytes(device_map)
            if data:
                return device_map, data
    pytest.skip(f"{filename} is not packaged")


def _map_selector(qtbot, filename, size):
    device_map, data = _packaged(filename)
    widget = KeySelector(device_map.rows, device_map.cols, DeviceGraphic(data), name=filename)
    qtbot.addWidget(widget)
    widget.resize(*size)
    widget.show()
    qtbot.waitExposed(widget)
    return widget, data


def _element_centre(data, cell, size):
    """Widget point at the centre of LED ``cell``, computed from the SVG alone."""
    renderer = QSvgRenderer(QByteArray(data))
    element_id = f"x{cell[1]}-y{cell[0]}"
    assert renderer.elementExists(element_id)
    centre = renderer.transformForElement(element_id).mapRect(
        renderer.boundsOnElement(element_id)).center()
    view = renderer.viewBoxF()
    area = QRectF(0, 0, *size).adjusted(EDGE, EDGE, -EDGE, -EDGE)
    scale = min(area.width() / view.width(), area.height() / view.height())
    left = area.left() + (area.width() - view.width() * scale) * HALF
    top = area.top() + (area.height() - view.height() * scale) * HALF
    return QPointF(left + (centre.x() - view.left()) * scale,
                   top + (centre.y() - view.top()) * scale).toPoint()


def test_keyboard_map_click_selects_led_under_pointer(qtbot):
    widget, data = _map_selector(qtbot, KEYBOARD_MAP, KEYBOARD_SIZE)
    for cell in KEYBOARD_KEYS:
        qtbot.mouseClick(widget, LEFT, Qt.KeyboardModifier.NoModifier,
                         _element_centre(data, cell, KEYBOARD_SIZE))
        assert widget.selection() == {cell}
    qtbot.mouseClick(widget, LEFT, Qt.KeyboardModifier.NoModifier, CORNER)
    assert widget.selection() == {KEYBOARD_KEYS[-1]}
    assert widget.cell_at(QPointF(CORNER)) is None


def test_mouse_map_click_selects_led_under_pointer(qtbot):
    widget, data = _map_selector(qtbot, MOUSE_MAP, MOUSE_SIZE)
    renderer = QSvgRenderer(QByteArray(data))
    drawn = sorted(cell for cell in widget.valid_cells()
                   if renderer.elementExists(f"x{cell[1]}-y{cell[0]}"))
    assert drawn and set(drawn) == widget.valid_cells()
    for cell in drawn:
        point = _element_centre(data, cell, MOUSE_SIZE)
        qtbot.mouseClick(widget, LEFT, Qt.KeyboardModifier.NoModifier, point)
        assert widget.selection() == {cell}
    assert widget.cell_at(QPointF(CORNER)) is None
    widget.repaint()  # painting the map with its LED rects must not fail


def test_colours_outlines_and_set_selection(qtbot, selector):
    selector.set_colours({(0, 0): (255, 0, 0)})
    selector.set_group_outlines({"WASD": [(2, 3)]})
    selector.set_selection([(0, 0), (99, 99)])
    assert selector.selection() == {(0, 0)}
    selector.repaint()  # painting with colours, outlines and focus must not fail
