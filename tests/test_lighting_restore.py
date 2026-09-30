# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the running-effect helpers of the lighting panel."""

import random
import threading

import pytest
from PyQt6.QtWidgets import QComboBox, QWidget

from hueberry.backend import advanced_preset_store, advanced_runtime, device_effects_store
from hueberry.backend import lighting_state
from hueberry.backend.advanced_presets import AdvancedPreset, DeviceProgram, KeyGroup
from hueberry.backend.advanced_runtime import AdvancedRuntime
from hueberry.backend.devices import MAIN_ZONE_KEY, ZoneInfo
from hueberry.backend.key_effects import KeyEffect
from hueberry.ui import lighting_restore
from hueberry.ui.colour_button import ColourButton

KBD = "KBD0001"
MATRIX_CAPS = ("lighting", "lighting_static", "lighting_led_matrix")
RED = (255, 0, 0)
BLUE = (0, 0, 255)
MAIN = ZoneInfo(MAIN_ZONE_KEY, "Main", "lighting", None)
PRESET = AdvancedPreset("wasd", "WASD glow", (DeviceProgram(KBD, (
    KeyGroup("WASD", ((2, 3), (3, 2)), KeyEffect(palette=(RED,))),)),))


@pytest.fixture
def runtime(monkeypatch):
    rt = AdvancedRuntime(start_thread=False, rng=random.Random(1))
    monkeypatch.setattr(advanced_runtime, "shared_runtime", lambda: rt)
    return rt


@pytest.fixture
def kbd(make_device):
    return make_device(name="Razer Keyboard", device_type="keyboard", serial=KBD,
                       capabilities=MATRIX_CAPS)


def test_record_for_needs_device_and_zone(kbd):
    assert lighting_restore.record_for(None, MAIN) is None
    assert lighting_restore.record_for(kbd, None) is None
    assert lighting_restore.record_for(kbd, MAIN) is None
    device_effects_store.save_record(KBD, MAIN_ZONE_KEY, "static", {"colour1": RED})
    assert lighting_restore.record_for(kbd, MAIN) == ("static", {"colour1": [255, 0, 0]})


def test_running_text_prefers_per_key_effect(runtime, kbd):
    assert lighting_restore.running_text(None, MAIN) is None
    assert lighting_restore.running_text(kbd, MAIN) is None
    device_effects_store.save_record(KBD, MAIN_ZONE_KEY, "spectrum", {})
    assert lighting_restore.running_text(kbd, MAIN) == "Running: Spectrum"
    runtime.activate(PRESET, [kbd])
    assert lighting_restore.running_text(kbd, MAIN) == "Running: wasd (Create effect)"
    advanced_preset_store.save([PRESET])
    assert lighting_restore.running_text(kbd, MAIN) == "Running: WASD glow (Create effect)"
    runtime.stop()
    assert lighting_restore.running_text(kbd, MAIN) == "Running: Spectrum"


def test_select_data_and_quiet_colour(qtbot):
    parent = QWidget()
    qtbot.addWidget(parent)
    combo = QComboBox(parent)
    combo.addItem("A", 1)
    combo.addItem("B", 2)
    changes = []
    combo.currentIndexChanged.connect(changes.append)
    assert lighting_restore.select_data(combo, 2)
    assert not lighting_restore.select_data(combo, 3)
    assert combo.currentData() == 2 and changes == []
    button = ColourButton("Primary colour", RED, parent)
    button.colour_changed.connect(changes.append)
    lighting_restore.set_colour_quietly(button, [0, 0, 255])
    assert button.colour() == BLUE and changes == []


def test_relay_refreshes_on_gui_thread_from_worker(qtbot, runtime, kbd):
    parent = QWidget()
    qtbot.addWidget(parent)
    calls = []
    relay = lighting_restore.RunningRelay(
        lambda: calls.append(threading.current_thread() is threading.main_thread()), parent)
    runtime.add_change_listener(relay.notify)
    thread = threading.Thread(target=runtime.activate, args=(PRESET, [kbd]))
    thread.start()
    thread.join()
    qtbot.waitUntil(lambda: calls == [True])


def test_connect_panel_watches_runtime_and_claims(qtbot, runtime):
    panel = QWidget()
    qtbot.addWidget(panel)
    calls = []
    panel.refresh_running = lambda: calls.append("refresh")
    lighting_restore.connect_panel(panel)
    lighting_state.shared_lighting_state().claim([KBD])
    qtbot.waitUntil(lambda: calls == ["refresh"])
