# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the live LED preview widget (offscreen)."""

from pathlib import Path

import pytest
from PyQt6.QtCore import QPointF

from hueberry.backend.effects import EFFECT_STATIC, EFFECT_WAVE, Preset, render_run
from hueberry.backend.device_maps import DeviceMap
from hueberry.backend.led_layout import DeviceShape, group_layout, single_layout
from hueberry.ui import led_preview, theme
from hueberry.ui.led_preview import LedPreview, PreviewDevice

KBD_SERIAL = "KBD0001"
MOUSE_SERIAL = "MOUSE0001"
PAD_SERIAL = "PAD0001"
ROWS = 6
COLS = 22
PHASE = 0.3
WIDGET_SIZE = (900, 300)
RED = (255, 0, 0)
BLUE = (0, 0, 255)
WAVE = Preset(key="wave", label="Wave", effect=EFFECT_WAVE, palette=(RED, BLUE))


def _devices():
    return [PreviewDevice(KBD_SERIAL, "Keyboard", "Keyboard",
                          DeviceShape.of_matrix(KBD_SERIAL, ROWS, COLS)),
            PreviewDevice(MOUSE_SERIAL, "Mouse", "MOUSE", DeviceShape.of_zones(MOUSE_SERIAL)),
            PreviewDevice(PAD_SERIAL, "Pad", "mousemat", DeviceShape.of_zones(PAD_SERIAL))]


@pytest.fixture
def preview(qtbot):
    widget = LedPreview()
    qtbot.addWidget(widget)
    widget.resize(*WIDGET_SIZE)
    widget.set_devices(_devices())
    widget.set_preset(WAVE)
    widget.set_phase(PHASE)
    return widget


def _assert_matches(widget, frames):
    for serial, frame in frames.items():
        for row, colours in enumerate(frame):
            for col, colour in enumerate(colours):
                assert widget.colour_at(serial, row, col) == colour


def test_group_colours_match_render_run(preview):
    preview.set_mode("group")
    shapes = [device.shape for device in _devices()]
    frames = render_run(WAVE, group_layout(shapes), PHASE)
    assert set(frames) == {KBD_SERIAL, MOUSE_SERIAL, PAD_SERIAL}
    _assert_matches(preview, frames)


def test_single_colours_match_render_run(preview):
    preview.set_mode("single")
    for device in _devices():
        frames = render_run(WAVE, single_layout(device.shape), PHASE)
        _assert_matches(preview, frames)
    assert preview.colour_at(KBD_SERIAL, ROWS, 0) is None  # outside the matrix


def test_group_rects_follow_order_without_overlap(preview):
    preview.set_mode("group")
    rects = preview.device_rects()
    assert list(rects) == [KBD_SERIAL, MOUSE_SERIAL, PAD_SERIAL]
    ordered = list(rects.values())
    for left, right in zip(ordered, ordered[1:]):
        assert left.right() < right.left()
        assert not left.intersects(right)
    assert all(rect.left() >= 0 and rect.right() <= WIDGET_SIZE[0] for rect in ordered)


def test_relative_widths_follow_nominal_sizes(preview):
    rects = preview.device_rects()
    kbd_w, kbd_h = led_preview.NOMINAL_SIZE_MM["keyboard"]
    mouse_w, mouse_h = led_preview.NOMINAL_SIZE_MM["mouse"]
    keyboard, mouse = rects[KBD_SERIAL], rects[MOUSE_SERIAL]
    assert keyboard.width() > mouse.width()
    assert keyboard.width() / mouse.width() == pytest.approx(kbd_w / mouse_w)
    assert keyboard.height() / mouse.height() == pytest.approx(kbd_h / mouse_h)


def test_unknown_type_uses_default_size():
    assert led_preview.nominal_size("Toaster") == led_preview.NOMINAL_SIZE_MM["default"]
    assert led_preview.nominal_size(" KeyBoard ") == led_preview.NOMINAL_SIZE_MM["keyboard"]


def test_timer_runs_only_while_shown(preview, qtbot):
    assert not preview.is_running()
    preview.show()
    qtbot.waitExposed(preview)
    assert preview.is_running()
    preview.hide()
    assert not preview.is_running()


def test_changing_preset_changes_colours(preview):
    preview.set_preset(Preset(key="red", label="Red", effect=EFFECT_STATIC, palette=(RED,)))
    before = preview.colour_at(KBD_SERIAL, 0, 0)
    preview.set_preset(Preset(key="blue", label="Blue", effect=EFFECT_STATIC, palette=(BLUE,)))
    assert preview.colour_at(KBD_SERIAL, 0, 0) != before


def test_accessible_text_describes_devices_mode_and_preset(preview):
    preview.set_mode("group")
    description = preview.accessibleDescription()
    assert preview.accessibleName() == "LED preview"
    assert "Keyboard" in description and "Mouse" in description
    assert "synced group" in description and "Wave" in description


def test_empty_and_presetless_render_without_error(qtbot):
    widget = LedPreview()
    qtbot.addWidget(widget)
    widget.resize(*WIDGET_SIZE)
    assert not widget.grab().isNull()
    assert widget.device_rects() == {}
    widget.set_devices(_devices())
    assert not widget.grab().isNull()
    assert widget.colour_at(KBD_SERIAL, 0, 0) is None


def test_preview_grab_with_preset(preview):
    assert not preview.grab().isNull()


FIXTURE_SVG = Path(__file__).parent / "fixtures" / "devicemaps" / "kbd_en_US.xml"
FIXTURE_NAME = "Fixture Kbd"
FIXTURE_SERIAL = "FIX0001"
FIXTURE_ROWS = 2
FIXTURE_COLS = 3
FIXTURE_MAP = DeviceMap(FIXTURE_NAME, FIXTURE_SVG.name, FIXTURE_ROWS, FIXTURE_COLS, "en_US")
LIT_LED_ID = "x0-y0"
PIXEL_TOLERANCE = 8
FIXTURE_LED_FILL = (0x80, 0x80, 0x80)  # the fixture LEDs' own fill


def _fixture_match(name, rows, cols, *args, **kwargs):
    if (name, rows, cols) == (FIXTURE_NAME, FIXTURE_ROWS, FIXTURE_COLS):
        return FIXTURE_MAP
    return None


def _lit_pixel(widget, pixmap):
    """The grabbed pixel at the centre of LED x0-y0 of the fixture graphic."""
    graphic = widget._graphics[FIXTURE_SERIAL]
    target = graphic.target_rect(widget.device_rects()[FIXTURE_SERIAL])
    size = graphic.default_size()
    centre = graphic.renderer.boundsOnElement(LIT_LED_ID).center()
    point = QPointF(target.left() + centre.x() * target.width() / size.width(),
                    target.top() + centre.y() * target.height() / size.height())
    ratio = pixmap.devicePixelRatio()
    return pixmap.toImage().pixelColor(int(point.x() * ratio), int(point.y() * ratio))


def _fixture_devices():
    return [PreviewDevice(FIXTURE_SERIAL, FIXTURE_NAME, "Keyboard",
                          DeviceShape.of_matrix(FIXTURE_SERIAL, FIXTURE_ROWS,
                                                FIXTURE_COLS))] + _devices()


def test_without_qtsvg_matched_device_falls_back_to_grid(qtbot, monkeypatch):
    """With QtSvg missing (DeviceGraphic None) a matched device draws the grid."""
    monkeypatch.setattr(led_preview, "DeviceGraphic", None)
    widget = _fixture_widget(qtbot, monkeypatch)
    assert widget._graphics == {}
    assert not widget.grab().isNull()


def _fixture_widget(qtbot, monkeypatch):
    """A preview whose fixture device is drawn from the fixture map."""
    monkeypatch.setattr(led_preview.device_maps, "match", _fixture_match)
    monkeypatch.setattr(led_preview.device_maps, "svg_bytes",
                        lambda device_map, *args, **kwargs: FIXTURE_SVG.read_bytes())
    widget = LedPreview()
    qtbot.addWidget(widget)
    widget.resize(*WIDGET_SIZE)
    widget.set_devices(_fixture_devices())
    return widget


def test_set_devices_reuses_graphics_of_the_same_map(qtbot, monkeypatch):
    widget = _fixture_widget(qtbot, monkeypatch)
    first = widget._graphics[FIXTURE_SERIAL]
    widget.set_devices(_fixture_devices())
    assert widget._graphics[FIXTURE_SERIAL] is first


def test_presetless_graphic_keeps_original_artwork(qtbot, monkeypatch):
    widget = _fixture_widget(qtbot, monkeypatch)
    pixel = _lit_pixel(widget, widget.grab())
    actual = (pixel.red(), pixel.green(), pixel.blue())
    assert all(abs(a - e) <= PIXEL_TOLERANCE for a, e in zip(actual, FIXTURE_LED_FILL))


def test_matched_device_is_drawn_from_its_graphic(qtbot, monkeypatch):
    widget = _fixture_widget(qtbot, monkeypatch)
    widget.set_preset(Preset(key="red", label="Red", effect=EFFECT_STATIC, palette=(RED,)))
    assert FIXTURE_SERIAL in widget._graphics
    assert KBD_SERIAL not in widget._graphics  # "Keyboard" 6x22 has no map
    pixmap = widget.grab()
    assert not pixmap.isNull()
    pixel = _lit_pixel(widget, pixmap)
    expected = widget.colour_at(FIXTURE_SERIAL, 0, 0)
    assert expected == RED
    actual = (pixel.red(), pixel.green(), pixel.blue())
    assert all(abs(a - e) <= PIXEL_TOLERANCE for a, e in zip(actual, expected))


def test_text_colours_meet_wcag_aa():
    for colour in (led_preview.NAME_COLOUR, led_preview.PLACEHOLDER_COLOUR):
        assert theme.contrast_ratio(colour, led_preview.BACKGROUND) >= theme.WCAG_AA_MIN_CONTRAST
