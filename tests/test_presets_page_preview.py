# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the live LED preview on the Presets page (offscreen, synchronous worker)."""

import pytest
from PyQt6.QtCore import Qt

from hueberry.backend import animator, lighting_state, preset_store
from hueberry.backend.devices import describe_device
from hueberry.backend.effects import EFFECT_BREATHE
from hueberry.ui import worker
from hueberry.ui.presets_page import PresetsPage

MATRIX_CAPS = ("lighting", "lighting_static", "lighting_led_matrix")
ZONE_CAPS = ("lighting", "lighting_static")
KBD_SERIAL = "KBD0001"
MOUSE_SERIAL = "MOUSE0001"
MAT_SERIAL = "MAT0001"
RED = (255, 0, 0)
SPEED_SLIDER_VALUE = 35  # 3.5 cycles/s


def _run_sync(fn, on_done=None, on_error=None):
    """Synchronous stand-in for worker.run_async."""
    try:
        result = fn()
    except Exception as exc:
        if on_error is not None:
            on_error(str(exc))
        return None
    if on_done is not None:
        on_done(result)
    return None


@pytest.fixture
def page(qtbot, tmp_path, monkeypatch):
    passive = animator.Animator(start_thread=False)
    monkeypatch.setattr(animator, "shared_animator", lambda: passive)
    state = lighting_state.LightingState(passive)
    monkeypatch.setattr(lighting_state, "shared_lighting_state", lambda: state)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(worker, "run_async", _run_sync)
    widget = PresetsPage()
    qtbot.addWidget(widget)
    return widget


@pytest.fixture
def entries(make_device):
    devs = [make_device(name="Keyboard", device_type="keyboard", serial=KBD_SERIAL,
                        capabilities=MATRIX_CAPS),
            make_device(name="Mouse", device_type="mouse", serial=MOUSE_SERIAL,
                        capabilities=ZONE_CAPS),
            make_device(name="Mat", device_type="mousemat", serial=MAT_SERIAL,
                        capabilities=ZONE_CAPS)]
    return [(dev, describe_device(dev)) for dev in devs]


def _preview(page):
    return page.preview.widget


def _serials(page):
    return [device.serial for device in _preview(page).devices()]


def test_preview_follows_selected_preset(page):
    assert _preview(page).preset() == page.editor.preset()
    page.new_button.click()
    assert _preview(page).preset().key == page.selected_key()


def test_editing_updates_preview_without_saving(page, entries):
    page.set_devices(entries)
    page.new_button.click()
    editor = page.editor
    editor.colour_buttons[0].set_colour(RED)
    assert _preview(page).preset().palette[0] == RED
    editor.speed_slider.setValue(SPEED_SLIDER_VALUE)
    assert _preview(page).preset().speed == pytest.approx(3.5)
    editor.effect_combo.setCurrentIndex(editor.effect_combo.findData(EFFECT_BREATHE))
    assert _preview(page).preset().effect == EFFECT_BREATHE
    assert _preview(page).preset() == editor.preset()
    assert not preset_store.config_path().exists()


def test_synced_group_switches_preview_mode(page):
    assert _preview(page).mode() == "single"
    page.group_radio.setChecked(True)
    assert _preview(page).mode() == "group"
    page.single_radio.setChecked(True)
    assert _preview(page).mode() == "single"


def test_every_listed_device_when_none_ticked(page, entries):
    page.set_devices(entries)
    assert _serials(page) == [KBD_SERIAL, MOUSE_SERIAL, MAT_SERIAL]


def test_ticking_two_devices_shows_both(page, entries):
    page.set_devices(entries)
    page.device_list.item(0).setCheckState(Qt.CheckState.Checked)
    assert _serials(page) == [KBD_SERIAL]
    page.device_list.item(2).setCheckState(Qt.CheckState.Checked)
    assert _serials(page) == [KBD_SERIAL, MAT_SERIAL]
    assert set(_preview(page).device_rects()) == {KBD_SERIAL, MAT_SERIAL}
    assert _preview(page).colour_at(KBD_SERIAL, 0, 0) is not None
