# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for painting device-map SVGs with LED colours (hand-made fixture map)."""

import xml.etree.ElementTree as ET
from importlib.resources import files
from pathlib import Path

import pytest
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter

from hueberry.backend import device_maps
from hueberry.ui.device_graphic import DeviceGraphic

FIXTURE = Path(__file__).parent / "fixtures" / "devicemaps" / "kbd_en_US.xml"
ROWS = 2
COLS = 3
EXPECTED_LEDS = {(row, col) for row in range(ROWS) for col in range(COLS)}
RED = QColor(255, 0, 0)
BLUE = QColor(0, 0, 255)
GREEN = QColor(0, 255, 0)
LIT = (0, 0)
LIT_ID = "x0-y0"
FIXED_ID = "fixed"  # the nochange node of LED x2-y1
IMAGE_SCALE = 4
TOLERANCE = 8
ORIGINAL_GREY = QColor(0x80, 0x80, 0x80)  # the fixture LEDs' own fill
REAL_MAP = "blackwidow_elite_en_US.svg"
REAL_LED_ID = "x14-y0"  # the F12 key
REAL_IMAGE_SIZE = (944, 373)
SVG_PREFIX = b"svg:"


@pytest.fixture
def graphic(qapp):
    return DeviceGraphic(FIXTURE.read_bytes())


def _one_red(row, col):
    return RED if (row, col) == LIT else BLUE


def _all_blue(row, col):
    return BLUE


def _all_red(row, col):
    return RED


def _lit_unset(row, col):
    return None if (row, col) == LIT else BLUE


def _render(graphic, colour_for):
    size = graphic.default_size() * IMAGE_SCALE
    image = QImage(size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        graphic.paint(painter, QRectF(image.rect()), colour_for)
    finally:
        painter.end()
    return image


def _pixel_at(graphic, image, element_id):
    centre = graphic.renderer.boundsOnElement(element_id).center()
    point = QPointF(centre.x() * IMAGE_SCALE, centre.y() * IMAGE_SCALE)
    return image.pixelColor(int(point.x()), int(point.y()))


def _close(actual, expected):
    return all(abs(a - e) <= TOLERANCE for a, e in
               zip((actual.red(), actual.green(), actual.blue()),
                   (expected.red(), expected.green(), expected.blue())))


def test_leds_are_indexed(graphic):
    assert graphic.leds() == EXPECTED_LEDS


def test_lit_led_shows_its_colour(graphic):
    image = _render(graphic, _one_red)
    assert _close(_pixel_at(graphic, image, LIT_ID), RED)
    assert _close(_pixel_at(graphic, image, "x1-y0"), BLUE)


def test_nochange_node_keeps_its_fill(graphic):
    image = _render(graphic, _all_blue)
    assert _close(_pixel_at(graphic, image, FIXED_ID), GREEN)


def test_renderer_reloads_only_when_colours_change(graphic):
    _render(graphic, _one_red)
    assert graphic.reload_count == 1
    _render(graphic, _one_red)
    assert graphic.reload_count == 1
    _render(graphic, _all_blue)
    assert graphic.reload_count == 2


def test_led_without_colour_keeps_original_styling(graphic):
    _render(graphic, _one_red)
    image = _render(graphic, _lit_unset)
    assert _close(_pixel_at(graphic, image, LIT_ID), ORIGINAL_GREY)
    assert _close(_pixel_at(graphic, image, "x1-y0"), BLUE)
    element = graphic._root.find(f".//*[@id='{LIT_ID}']")
    assert element.get("style") == "fill:#808080;stroke:#000000"


def test_uncoloured_cache_key_includes_none(graphic):
    _render(graphic, _one_red)
    _render(graphic, _lit_unset)
    _render(graphic, _lit_unset)
    assert graphic.reload_count == 2


def _real_map_bytes():
    resource = files("hueberry.data") / "devicemaps" / REAL_MAP
    if not resource.is_file():
        pytest.skip(f"{REAL_MAP} is not packaged")
    return resource.read_bytes()


def _mapped_centre(graphic, image, element_id):
    """Image pixel at the centre of ``element_id``, mapped through viewBox and target_rect."""
    renderer = graphic.renderer
    bounds = renderer.transformForElement(element_id).mapRect(
        renderer.boundsOnElement(element_id))
    view = renderer.viewBoxF()
    target = graphic.target_rect(QRectF(image.rect()))
    centre = bounds.center()
    x = target.left() + (centre.x() - view.left()) * target.width() / view.width()
    y = target.top() + (centre.y() - view.top()) * target.height() / view.height()
    return image.pixelColor(int(x), int(y))


def test_real_map_paints_leds_without_svg_prefix(qapp):
    graphic = DeviceGraphic(_real_map_bytes())
    image = QImage(*REAL_IMAGE_SIZE, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        graphic.paint(painter, QRectF(image.rect()), _all_red)
    finally:
        painter.end()
    assert graphic.renderer.elementExists(REAL_LED_ID)
    assert _close(_mapped_centre(graphic, image, REAL_LED_ID), RED)
    assert SVG_PREFIX not in ET.tostring(graphic._root)


def test_invalid_svg_raises(qapp):
    with pytest.raises(ValueError):
        DeviceGraphic(b"not svg")


def test_every_packaged_map_builds(qapp):
    index = device_maps.load_index()
    if not index:
        pytest.skip("no packaged device maps")
    violators = []
    for name, device_map in sorted(index.items()):
        leds = DeviceGraphic(device_maps.svg_bytes(device_map)).leds()
        assert leds, f"{device_map.filename} has no LEDs"
        outside = sorted(led for led in leds
                         if not (led[0] < device_map.rows and led[1] < device_map.cols))
        if outside:
            violators.append(f"{name} ({device_map.filename}): {outside}")
    assert not violators, "LEDs outside the matrix: " + "; ".join(violators)
