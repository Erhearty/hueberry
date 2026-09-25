# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Generic device-type icons drawn with QPainter (no image files).

Shapes are drawn on a square design grid of ``CANVAS`` units and scaled to the
requested size, with a single stroke colour (the theme accent by default).
"""

from typing import Callable

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

from hueberry.ui import theme

KIND_MOUSE = "mouse"
KIND_KEYBOARD = "keyboard"
KIND_HEADSET = "headset"
KIND_MOUSEMAT = "mousemat"
KIND_KEYPAD = "keypad"
KIND_GENERIC = "generic"
# Checked in order: the mousemat entries must come before "mouse".
TYPE_SUBSTRINGS = (
    ("mousemat", KIND_MOUSEMAT),
    ("mousepad", KIND_MOUSEMAT),
    ("mouse", KIND_MOUSE),
    ("keyboard", KIND_KEYBOARD),
    ("keypad", KIND_KEYPAD),
    ("headset", KIND_HEADSET),
    ("headphone", KIND_HEADSET),
)

DEFAULT_SIZE = 64
CANVAS = 64.0
STROKE_WIDTH = 3.0
HALF_CIRCLE = 180
QT_ANGLE_UNITS = 16  # QPainter arc angles are in 1/16 degree

# Geometry on the design grid: rects are (x, y, width, height).
MOUSE_BODY = (18.0, 6.0, 28.0, 52.0)
MOUSE_RADIUS = 14.0
MOUSE_SPLIT = ((32.0, 6.0), (32.0, 24.0))
MOUSE_WHEEL = (29.0, 11.0, 6.0, 9.0)
MOUSE_WHEEL_RADIUS = 3.0
KEYBOARD_BODY = (4.0, 16.0, 56.0, 32.0)
KEYBOARD_RADIUS = 4.0
KEYBOARD_KEYS = (2, 6)  # rows, columns
KEYBOARD_KEY_ORIGIN = (9.0, 21.0)
KEYBOARD_KEY_STEP = 8.0
KEY_SIZE = 5.0
KEYBOARD_SPACEBAR = ((18.0, 41.0), (46.0, 41.0))
HEADSET_BAND = (12.0, 8.0, 40.0, 40.0)
HEADSET_CUPS = ((7.0, 28.0, 12.0, 20.0), (45.0, 28.0, 12.0, 20.0))
HEADSET_CUP_RADIUS = 4.0
MOUSEMAT_PAD = (4.0, 12.0, 56.0, 40.0)
MOUSEMAT_RADIUS = 6.0
MOUSEMAT_MOUSE = (38.0, 20.0, 12.0, 22.0)
MOUSEMAT_MOUSE_RADIUS = 6.0
KEYPAD_BODY = (12.0, 6.0, 40.0, 52.0)
KEYPAD_RADIUS = 5.0
KEYPAD_KEYS = (3, 3)  # rows, columns
KEYPAD_KEY_ORIGIN = (18.0, 12.0)
KEYPAD_KEY_STEP = 10.0
KEYPAD_KEY_SIZE = 7.0
KEYPAD_THUMB = (32.0, 48.0)
KEYPAD_THUMB_RADIUS = 4.0
GENERIC_BODY = (8.0, 14.0, 48.0, 32.0)
GENERIC_RADIUS = 6.0
GENERIC_DOT = (32.0, 30.0)
GENERIC_DOT_RADIUS = 5.0
GENERIC_BASE = ((22.0, 53.0), (42.0, 53.0))


def kind_for_type(device_type: str) -> str:
    """Map a daemon device type string to an icon kind (case-insensitive substring)."""
    lowered = (device_type or "").lower()
    for substring, kind in TYPE_SUBSTRINGS:
        if substring in lowered:
            return kind
    return KIND_GENERIC


def _rect(geometry: tuple) -> QRectF:
    return QRectF(*geometry)


def _line(painter: QPainter, points: tuple) -> None:
    start, end = points
    painter.drawLine(QPointF(*start), QPointF(*end))


def _key_grid(painter: QPainter, shape: tuple, origin: tuple, step: float, size: float) -> None:
    """Draw a filled grid of square keys."""
    rows, columns = shape
    left, top = origin
    colour = painter.pen().color()
    for row in range(rows):
        for column in range(columns):
            painter.fillRect(QRectF(left + column * step, top + row * step, size, size), colour)


def _draw_mouse(painter: QPainter) -> None:
    painter.drawRoundedRect(_rect(MOUSE_BODY), MOUSE_RADIUS, MOUSE_RADIUS)
    _line(painter, MOUSE_SPLIT)
    painter.drawRoundedRect(_rect(MOUSE_WHEEL), MOUSE_WHEEL_RADIUS, MOUSE_WHEEL_RADIUS)


def _draw_keyboard(painter: QPainter) -> None:
    painter.drawRoundedRect(_rect(KEYBOARD_BODY), KEYBOARD_RADIUS, KEYBOARD_RADIUS)
    _key_grid(painter, KEYBOARD_KEYS, KEYBOARD_KEY_ORIGIN, KEYBOARD_KEY_STEP, KEY_SIZE)
    _line(painter, KEYBOARD_SPACEBAR)


def _draw_headset(painter: QPainter) -> None:
    painter.drawArc(_rect(HEADSET_BAND), 0, HALF_CIRCLE * QT_ANGLE_UNITS)
    for cup in HEADSET_CUPS:
        painter.drawRoundedRect(_rect(cup), HEADSET_CUP_RADIUS, HEADSET_CUP_RADIUS)


def _draw_mousemat(painter: QPainter) -> None:
    painter.drawRoundedRect(_rect(MOUSEMAT_PAD), MOUSEMAT_RADIUS, MOUSEMAT_RADIUS)
    painter.drawRoundedRect(_rect(MOUSEMAT_MOUSE), MOUSEMAT_MOUSE_RADIUS, MOUSEMAT_MOUSE_RADIUS)


def _draw_keypad(painter: QPainter) -> None:
    painter.drawRoundedRect(_rect(KEYPAD_BODY), KEYPAD_RADIUS, KEYPAD_RADIUS)
    _key_grid(painter, KEYPAD_KEYS, KEYPAD_KEY_ORIGIN, KEYPAD_KEY_STEP, KEYPAD_KEY_SIZE)
    painter.drawEllipse(QPointF(*KEYPAD_THUMB), KEYPAD_THUMB_RADIUS, KEYPAD_THUMB_RADIUS)


def _draw_generic(painter: QPainter) -> None:
    painter.drawRoundedRect(_rect(GENERIC_BODY), GENERIC_RADIUS, GENERIC_RADIUS)
    painter.drawEllipse(QPointF(*GENERIC_DOT), GENERIC_DOT_RADIUS, GENERIC_DOT_RADIUS)
    _line(painter, GENERIC_BASE)


_DRAWERS: dict[str, Callable[[QPainter], None]] = {
    KIND_MOUSE: _draw_mouse,
    KIND_KEYBOARD: _draw_keyboard,
    KIND_HEADSET: _draw_headset,
    KIND_MOUSEMAT: _draw_mousemat,
    KIND_KEYPAD: _draw_keypad,
    KIND_GENERIC: _draw_generic,
}


def pixmap_for_type(device_type: str, size: int = DEFAULT_SIZE,
                    colour: QColor | str | None = None) -> QPixmap:
    """Draw the icon for ``device_type`` on a transparent ``size``x``size`` pixmap."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    pen = QPen(QColor(colour if colour is not None else theme.ACCENT))
    pen.setWidthF(STROKE_WIDTH)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(size / CANVAS, size / CANVAS)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        _DRAWERS[kind_for_type(device_type)](painter)
    finally:
        painter.end()
    return pixmap


def icon_for_type(device_type: str, size: int = DEFAULT_SIZE,
                  colour: QColor | str | None = None) -> QIcon:
    """Return a QIcon for ``device_type`` (see :func:`pixmap_for_type`)."""
    return QIcon(pixmap_for_type(device_type, size, colour))
