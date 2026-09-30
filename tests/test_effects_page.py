# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the Effects page (offscreen, synchronous worker, fake runtime)."""

import pytest

from hueberry.backend import advanced_preset_store, advanced_runtime
from hueberry.backend.devices import describe_device
from hueberry.backend.key_effects import EFFECT_WAVE
from hueberry.settings import LAST_ADVANCED_PRESET, Settings
from hueberry.ui import worker
from hueberry.ui.effects_groups import add_group, assign_keys, next_group_name, remove_group
from hueberry.ui.effects_page import EffectsPage

MATRIX_CAPS = ("lighting", "lighting_static", "lighting_led_matrix")
ZONE_CAPS = ("lighting", "lighting_static")
KBD = "KBD0001"
MOUSE = "MOUSE0001"
WASD = {(2, 3), (3, 2), (3, 3), (3, 4)}
ESC = {(0, 1)}


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


class FakeRuntime:
    """Records the calls of the page."""

    def __init__(self) -> None:
        self.activated = []
        self.updated = []
        self.stopped = 0
        self.key = None

    def activate(self, preset, devices):
        self.activated.append((preset, list(devices)))
        self.key = preset.key
        return [program.serial for program in preset.programs]

    def update(self, preset):
        self.updated.append(preset)
        return preset.key == self.key

    def stop(self):
        self.stopped += 1
        self.key = None

    def active_key(self):
        return self.key


@pytest.fixture
def runtime(monkeypatch):
    fake = FakeRuntime()
    monkeypatch.setattr(advanced_runtime, "shared_runtime", lambda: fake)
    return fake


@pytest.fixture
def settings(tmp_path):
    return Settings(tmp_path / "settings.json")


@pytest.fixture
def page(qtbot, monkeypatch, runtime, settings, make_device):
    monkeypatch.setattr(worker, "run_async", _run_sync)
    widget = EffectsPage(settings)
    qtbot.addWidget(widget)
    widget.messages = []
    widget.status.connect(widget.messages.append)
    devs = [make_device(name="Razer Keyboard", serial=KBD, capabilities=MATRIX_CAPS),
            make_device(name="Razer Mouse", serial=MOUSE, capabilities=ZONE_CAPS)]
    widget.set_devices([(dev, describe_device(dev)) for dev in devs])
    return widget


def _make_group(page, cells):
    page.selector().set_selection(cells)
    page.groups.add_button.click()


def test_lists_only_matrix_devices(page):
    assert page.device_list.count() == 1
    assert page.current_serial() == KBD
    assert page.selector().accessibleName()


def test_create_groups_from_selection(page):
    _make_group(page, WASD)
    _make_group(page, ESC | {(2, 3)})  # takes W from the first group
    program = page.current_preset().program_for(KBD)
    assert [g.name for g in program.groups] == ["Group 1", "Group 2"]
    assert set(program.groups[0].leds) == WASD - {(2, 3)}
    assert set(program.groups[1].leds) == ESC | {(2, 3)}
    assert page.groups.group_list.count() == 2
    assert page.preset_combo.currentText().endswith("*")


def test_choosing_group_selects_its_keys_and_assign_rename_remove(page):
    _make_group(page, WASD)
    _make_group(page, ESC)
    page.groups.group_list.setCurrentRow(0)
    assert page.selector().selection() == frozenset(WASD)
    page.selector().set_selection({(0, 0)})
    page.groups.assign_button.click()
    page.groups.name_edit.setText("Keys")
    page.groups.rename_button.click()
    program = page.current_preset().program_for(KBD)
    assert program.groups[0].leds == ((0, 0),) and program.groups[0].name == "Keys"
    page.groups.remove_button.click()
    assert [g.name for g in page.current_preset().program_for(KBD).groups] == ["Group 2"]


def test_edit_effect_updates_group_and_preview(page):
    _make_group(page, WASD)
    combo = page.groups.editor.effect_combo
    combo.setCurrentIndex(combo.findData(EFFECT_WAVE))
    group = page.current_preset().program_for(KBD).groups[0]
    assert group.effect.effect == EFFECT_WAVE
    page.render_preview()
    assert set(page.selector()._colours) == WASD


def test_save_and_load(page, settings, runtime, qtbot):
    _make_group(page, WASD)
    page.label_edit.setText("Gaming")
    page.label_edit.textEdited.emit("Gaming")
    page.save()
    saved, error = advanced_preset_store.load()
    assert error is None and [p.label for p in saved] == ["Gaming"]
    assert not page.preset_combo.currentText().endswith("*")
    page.save_as()
    assert len(advanced_preset_store.load()[0]) == 2
    reloaded = EffectsPage(settings)
    qtbot.addWidget(reloaded)
    reloaded.select_preset(saved[0].key)
    assert reloaded.current_preset() == saved[0]
    page.delete()
    assert len(advanced_preset_store.load()[0]) == 1


def test_activate_calls_runtime_and_sets_setting(page, runtime, settings):
    _make_group(page, WASD)
    page.activate()
    preset, devs = runtime.activated[-1]
    assert preset.key == page.current_preset().key
    assert [d.serial for d in devs] == [KBD]
    assert Settings(settings.path).get(LAST_ADVANCED_PRESET) == preset.key
    _make_group(page, ESC)  # a live edit reaches the runtime
    assert runtime.updated[-1].program_for(KBD).groups[-1].leds == ((0, 1),)


def test_stop_clears_setting(page, runtime, settings):
    _make_group(page, WASD)
    page.activate()
    page.stop()
    assert runtime.stopped == 1
    assert Settings(settings.path).get(LAST_ADVANCED_PRESET) == ""


def test_activate_without_connected_devices_reports(page, runtime):
    page.set_devices([])
    page.activate()
    assert not runtime.activated
    assert page.messages


def test_preview_runs_only_while_visible(page):
    assert not page.preview_running()
    page.show()
    assert page.preview_running()
    page.hide()
    assert not page.preview_running()


def test_program_helpers():
    from hueberry.backend.advanced_presets import DeviceProgram

    program = add_group(DeviceProgram(KBD), WASD)
    assert next_group_name(program) == "Group 2"
    program = add_group(program, ESC)
    program = assign_keys(program, 1, WASD)
    assert program.groups[0].leds == ()
    assert remove_group(program, 0).groups[0].name == "Group 2"
