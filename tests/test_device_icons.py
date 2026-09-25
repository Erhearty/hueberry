# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the QPainter-drawn device-type icons (offscreen)."""

import pytest
from PyQt6.QtGui import QColor

from hueberry.ui import device_icons, theme
from hueberry.ui.device_icons import icon_for_type, kind_for_type, pixmap_for_type

ICON_SIZE = 48
OPAQUE_MIN = 200
CHANNEL_TOLERANCE = 8
CUSTOM_COLOUR = "#ff0000"


@pytest.mark.parametrize(("device_type", "kind"), [
    ("mouse", device_icons.KIND_MOUSE),
    ("MOUSE", device_icons.KIND_MOUSE),
    ("mousemat", device_icons.KIND_MOUSEMAT),
    ("Mousemat", device_icons.KIND_MOUSEMAT),
    ("keyboard", device_icons.KIND_KEYBOARD),
    ("Keyboard", device_icons.KIND_KEYBOARD),
    ("headset", device_icons.KIND_HEADSET),
    ("keypad", device_icons.KIND_KEYPAD),
    ("Unknown", device_icons.KIND_GENERIC),
    ("", device_icons.KIND_GENERIC),
    ("mug", device_icons.KIND_GENERIC),
])
def test_kind_for_type(device_type, kind):
    assert kind_for_type(device_type) == kind


def _has_colour(image, colour: QColor) -> bool:
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = image.pixelColor(x, y)
            if pixel.alpha() < OPAQUE_MIN:
                continue
            channels = zip((pixel.red(), pixel.green(), pixel.blue()),
                           (colour.red(), colour.green(), colour.blue()))
            if all(abs(a - b) <= CHANNEL_TOLERANCE for a, b in channels):
                return True
    return False


def test_icon_has_requested_size(qapp):
    icon = icon_for_type("mouse", ICON_SIZE)
    assert not icon.isNull()
    pixmap = pixmap_for_type("mouse", ICON_SIZE)
    assert (pixmap.width(), pixmap.height()) == (ICON_SIZE, ICON_SIZE)


def test_background_transparent_and_accent_stroke(qapp):
    image = pixmap_for_type("keyboard", ICON_SIZE).toImage()
    assert image.pixelColor(0, 0).alpha() == 0
    assert _has_colour(image, QColor(theme.ACCENT))


def test_custom_colour(qapp):
    image = pixmap_for_type("headset", ICON_SIZE, CUSTOM_COLOUR).toImage()
    assert _has_colour(image, QColor(CUSTOM_COLOUR))
    assert not _has_colour(image, QColor(theme.ACCENT))


def test_kinds_draw_different_shapes(qapp):
    images = [pixmap_for_type(kind, ICON_SIZE).toImage()
              for kind in ("mouse", "keyboard", "headset", "mousemat", "keypad", "Unknown")]
    for index, image in enumerate(images):
        for other in images[index + 1:]:
            assert image != other
