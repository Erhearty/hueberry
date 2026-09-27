# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for mapping the lighting panel's selection to an LED preview preset (offscreen)."""

import pytest

from hueberry.backend.effects import (
    DIRECTION_FORWARD, DIRECTION_REVERSE, EFFECT_BREATHE, EFFECT_CYCLE, EFFECT_PER_KEY,
    EFFECT_STATIC, MAX_BRIGHTNESS,
)
from hueberry.backend.lighting import WAVE_LEFT, WAVE_RIGHT
from hueberry.ui import worker
from hueberry.ui.lighting_panel import PRESET_ERHEART, LightingPanel
from hueberry.ui.lighting_preview import HUE_PALETTE, preview_preset

MATRIX_CAPS = ("lighting", "lighting_static", "lighting_breath_dual", "lighting_led_matrix",
               "lighting_spectrum", "lighting_wave", "lighting_none")
BRIGHTNESS_CAPS = MATRIX_CAPS + ("brightness",)
COLOUR1 = (10, 20, 30)
COLOUR2 = (40, 50, 60)
SLIDER_VALUE = 40
EXPECTED_BRIGHTNESS = 0.4


@pytest.fixture(autouse=True)
def no_writes(monkeypatch):
    """Device writes (brightness) never start a real worker."""
    monkeypatch.setattr(worker, "run_async", lambda fn, on_done=None, on_error=None: None)


def _make_panel(qtbot, make_device, capabilities=MATRIX_CAPS):
    panel = LightingPanel()
    qtbot.addWidget(panel)
    panel.set_device(make_device(device_type="keyboard", capabilities=capabilities))
    panel.colour1_button.set_colour(COLOUR1)
    panel.colour2_button.set_colour(COLOUR2)
    return panel


def _select(panel, data):
    index = panel.effect_combo.findData(data)
    assert index >= 0, data
    panel.effect_combo.setCurrentIndex(index)


def _select_direction(panel, value):
    panel.direction_combo.setCurrentIndex(panel.direction_combo.findData(value))


def test_static_maps_to_static_colour1(qtbot, make_device):
    panel = _make_panel(qtbot, make_device)
    _select(panel, "static")
    preset = preview_preset(panel)
    assert preset.effect == EFFECT_STATIC
    assert preset.palette == (COLOUR1,)
    preset.validate()


def test_breath_dual_maps_to_breathe_both_colours(qtbot, make_device):
    panel = _make_panel(qtbot, make_device)
    _select(panel, "breath_dual")
    preset = preview_preset(panel)
    assert preset.effect == EFFECT_BREATHE
    assert preset.palette == (COLOUR1, COLOUR2)


def test_spectrum_maps_to_cycle(qtbot, make_device):
    panel = _make_panel(qtbot, make_device)
    _select(panel, "spectrum")
    preset = preview_preset(panel)
    assert preset.effect == EFFECT_CYCLE
    assert preset.palette == HUE_PALETTE
    preset.validate()


def test_wave_direction(qtbot, make_device):
    panel = _make_panel(qtbot, make_device)
    _select(panel, "wave")
    _select_direction(panel, WAVE_LEFT)
    preset = preview_preset(panel)
    assert preset.effect == EFFECT_PER_KEY
    assert preset.direction == DIRECTION_REVERSE
    _select_direction(panel, WAVE_RIGHT)
    assert preview_preset(panel).direction == DIRECTION_FORWARD


def test_off_has_no_preview(qtbot, make_device):
    panel = _make_panel(qtbot, make_device)
    _select(panel, "none")
    assert preview_preset(panel) is None


def test_no_device_has_no_preview(qtbot):
    panel = LightingPanel()
    qtbot.addWidget(panel)
    assert preview_preset(panel) is None


def test_selected_preset_returned_unchanged(qtbot, make_device):
    panel = _make_panel(qtbot, make_device)
    _select(panel, PRESET_ERHEART)
    selected = panel.selected_preset()
    assert selected is not None
    assert preview_preset(panel) is selected


def test_brightness_follows_slider(qtbot, make_device):
    panel = _make_panel(qtbot, make_device, BRIGHTNESS_CAPS)
    _select(panel, "static")
    assert panel.brightness_slider.isEnabled()
    panel.brightness_slider.setValue(SLIDER_VALUE)
    assert preview_preset(panel).brightness == pytest.approx(EXPECTED_BRIGHTNESS)


def test_brightness_full_when_slider_disabled(qtbot, make_device):
    panel = _make_panel(qtbot, make_device)
    _select(panel, "static")
    assert not panel.brightness_slider.isEnabled()
    assert preview_preset(panel).brightness == MAX_BRIGHTNESS


def test_preview_changed_on_effect_change(qtbot, make_device):
    panel = _make_panel(qtbot, make_device)
    _select(panel, "static")
    with qtbot.waitSignal(panel.preview_changed, timeout=0):
        _select(panel, "spectrum")


def test_preview_changed_on_colour(qtbot, make_device):
    panel = _make_panel(qtbot, make_device)
    with qtbot.waitSignal(panel.preview_changed, timeout=0):
        panel.colour1_button.set_colour(COLOUR2)


def test_preview_changed_on_brightness(qtbot, make_device):
    panel = _make_panel(qtbot, make_device, BRIGHTNESS_CAPS)
    with qtbot.waitSignal(panel.preview_changed, timeout=0):
        panel.brightness_slider.setValue(SLIDER_VALUE)
