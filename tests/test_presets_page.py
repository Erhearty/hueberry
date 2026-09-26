# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the Presets page and the preset editor (offscreen, synchronous worker)."""

import json

import pytest
from PyQt6.QtCore import Qt

from hueberry.backend import animator, lighting_state, preset_store, presets
from hueberry.backend.devices import describe_device
from hueberry.backend.effects import EFFECT_BREATHE, Preset
from hueberry.ui import presets_actions, worker
from hueberry.ui.preset_editor import PresetEditor
from hueberry.ui.presets_page import BUILTIN_SUFFIX, PresetsPage

MATRIX_CAPS = ("lighting", "lighting_static", "lighting_led_matrix")
ZONE_CAPS = ("lighting", "lighting_static")
UNSUPPORTED_CAPS = ("dpi",)
KBD_SERIAL = "KBD0001"
MOUSE_SERIAL = "MOUSE0001"
PLAIN_SERIAL = "PLAIN0001"
RED = (255, 0, 0)
SPEED_SLIDER_VALUE = 35  # 3.5 cycles/s
BRIGHTNESS_SLIDER_VALUE = 40  # 40 %


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
def anim(monkeypatch):
    """A passive animator installed as the shared one."""
    passive = animator.Animator(start_thread=False)
    monkeypatch.setattr(animator, "shared_animator", lambda: passive)
    state = lighting_state.LightingState(passive)
    monkeypatch.setattr(lighting_state, "shared_lighting_state", lambda: state)
    return passive


@pytest.fixture
def page(qtbot, tmp_path, monkeypatch, anim):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(worker, "run_async", _run_sync)
    widget = PresetsPage()
    qtbot.addWidget(widget)
    messages = []
    widget.status.connect(messages.append)
    widget.messages = messages
    return widget


@pytest.fixture
def devices(make_device):
    return [make_device(name="Keyboard", serial=KBD_SERIAL, capabilities=MATRIX_CAPS),
            make_device(name="Mouse", serial=MOUSE_SERIAL, capabilities=ZONE_CAPS),
            make_device(name="Plain", serial=PLAIN_SERIAL, capabilities=UNSUPPORTED_CAPS)]


def _entries(devs):
    return [(dev, describe_device(dev)) for dev in devs]


def _saved():
    return json.loads(preset_store.config_path().read_text())


def _list_texts(page):
    return [page.preset_list.item(row).text() for row in range(page.preset_list.count())]


def _tick_all(page):
    for row in range(page.device_list.count()):
        page.device_list.item(row).setCheckState(Qt.CheckState.Checked)


def test_builtin_listed_and_read_only(page):
    assert _list_texts(page)[0] == presets.PRESET_LABEL + BUILTIN_SUFFIX
    assert page.selected_key() == presets.PRESET_KEY
    editor = page.editor
    assert not editor.label_edit.isEnabled()
    assert not editor.effect_combo.isEnabled()
    assert not editor.add_colour_button.isEnabled()
    assert all(not button.isEnabled() for button in editor.colour_buttons)
    assert page.duplicate_button.isEnabled()
    assert not page.delete_button.isEnabled()


def test_duplicate_builtin_makes_editable_copy(page):
    page.duplicate_button.click()
    copy = page.editor.preset()
    assert not copy.builtin
    assert copy.key != presets.PRESET_KEY
    assert copy.palette == presets.PALETTE
    assert page.editor.label_edit.isEnabled()
    assert page.delete_button.isEnabled()


def test_create_edit_save_writes_file(page, qtbot):
    page.new_button.click()
    editor = page.editor
    editor.label_edit.setText("Sunset")
    editor.colour_buttons[0].set_colour(RED)
    editor.effect_combo.setCurrentIndex(editor.effect_combo.findData(EFFECT_BREATHE))
    editor.speed_slider.setValue(SPEED_SLIDER_VALUE)
    editor.brightness_slider.setValue(BRIGHTNESS_SLIDER_VALUE)
    with qtbot.waitSignal(page.presets_saved, timeout=0):
        page.save_button.click()
    (entry,) = _saved()["presets"]
    assert entry["label"] == "Sunset"
    assert entry["palette"][0] == "#ff0000"
    assert entry["effect"] == EFFECT_BREATHE
    assert entry["speed"] == pytest.approx(3.5)
    assert entry["brightness"] == pytest.approx(0.4)
    assert page.messages[-1] == "Presets saved"
    assert not page.save_button.isEnabled()


def test_delete_user_preset(page):
    page.new_button.click()
    page.save_button.click()
    assert len(_saved()["presets"]) == 1
    page.delete_button.click()
    page.save_button.click()
    assert _saved()["presets"] == []
    assert page.selected_key() == presets.PRESET_KEY


def test_save_error_reaches_status(page):
    page.new_button.click()
    page.editor.label_edit.setText("   ")
    page.save_button.click()
    assert page.messages[-1].startswith("Saving presets failed:")
    assert not preset_store.config_path().exists()


def test_editor_emits_on_every_edit(qtbot):
    editor = PresetEditor()
    qtbot.addWidget(editor)
    seen = []
    editor.preset_changed.connect(seen.append)
    editor.set_preset(Preset(key="mine", label="Mine", effect="wave", palette=(RED,)))
    assert seen == []  # loading a preset does not emit
    editor.label_edit.setText("Renamed")
    editor.colour_buttons[0].set_colour((0, 0, 255))
    editor.add_colour_button.click()
    editor.remove_colour_button.click()
    editor.effect_combo.setCurrentIndex(editor.effect_combo.findData(EFFECT_BREATHE))
    editor.speed_slider.setValue(SPEED_SLIDER_VALUE)
    editor.direction_combo.setCurrentIndex(1)
    editor.brightness_slider.setValue(BRIGHTNESS_SLIDER_VALUE)
    assert len(seen) == 8
    last = seen[-1]
    assert (last.label, last.palette, last.direction) == ("Renamed", ((0, 0, 255),), "reverse")
    assert not editor.remove_colour_button.isEnabled()  # one colour is the minimum


def test_only_supported_devices_listed(page, devices):
    page.set_devices(_entries(devices))
    serials = [page.device_list.item(row).data(Qt.ItemDataRole.UserRole)
               for row in range(page.device_list.count())]
    assert serials == [KBD_SERIAL, MOUSE_SERIAL]


def test_apply_single_runs_each_device(page, anim, devices):
    page.set_devices(_entries(devices))
    _tick_all(page)
    page.single_radio.setChecked(True)
    page.apply_button.click()
    runs = anim.runs()
    assert sorted(run.serials for run in runs) == [(KBD_SERIAL,), (MOUSE_SERIAL,)]
    assert not any(run.grouped for run in runs)
    assert page.messages[-1] == "Erheart applied to 2 device(s)"


def test_apply_group_is_one_synced_run(page, anim, devices):
    page.set_devices(_entries(devices))
    _tick_all(page)
    page.group_radio.setChecked(True)
    page.apply_button.click()
    (run,) = anim.runs()
    assert run.grouped
    assert run.serials == (KBD_SERIAL, MOUSE_SERIAL)


def test_stop_checked_devices(page, anim, devices):
    page.set_devices(_entries(devices))
    _tick_all(page)
    page.apply_button.click()
    page.stop_button.click()
    assert anim.runs() == []
    assert page.messages[-1] == "Stopped 2 device(s)"


def test_saving_running_preset_updates_animation(page, anim, devices):
    page.new_button.click()
    page.save_button.click()
    key = page.selected_key()
    page.set_devices(_entries(devices[:1]))
    _tick_all(page)
    page.apply_button.click()
    assert anim.running_preset(KBD_SERIAL) == key
    page.editor.colour_buttons[0].set_colour(RED)
    page.save_button.click()
    (run,) = anim.runs()
    assert run.preset.key == key
    assert run.preset.palette[0] == RED


def test_apply_unsaved_preset_notes_it(page, devices):
    page.new_button.click()
    page.set_devices(_entries(devices[:1]))
    _tick_all(page)
    page.apply_button.click()
    assert page.messages[-1].endswith(presets_actions.UNSAVED_NOTE)
    assert lighting_state.shared_lighting_state().assignments()[0].preset_key \
        == page.selected_key()


def test_delete_forgets_assignment_on_save(page, anim, devices):
    page.new_button.click()
    page.save_button.click()
    key = page.selected_key()
    page.set_devices(_entries(devices[:1]))
    _tick_all(page)
    page.apply_button.click()
    assert page.messages[-1] == "New preset applied to 1 device(s)"
    page.delete_button.click()
    state = lighting_state.shared_lighting_state()
    assert [a.preset_key for a in state.assignments()] == [key]  # not saved yet
    assert anim.running_preset(KBD_SERIAL) == key
    page.save_button.click()
    assert state.assignments() == []
    assert anim.running_preset(KBD_SERIAL) is None


def test_ticks_survive_device_reload(page, devices):
    page.set_devices(_entries(devices))
    page.device_list.item(1).setCheckState(Qt.CheckState.Checked)
    page.set_devices(_entries(devices))
    assert page.checked_serials() == [MOUSE_SERIAL]
