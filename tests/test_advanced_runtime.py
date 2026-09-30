# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the advanced (per-key) preset runtime."""

import random

import pytest

from hueberry.backend import advanced_runtime, lighting_state
from hueberry.backend.advanced_presets import AdvancedPreset, DeviceProgram, KeyGroup
from hueberry.backend.advanced_runtime import AdvancedRuntime
from hueberry.backend.key_effects import EFFECT_REACTIVE, KeyEffect

MATRIX_CAPS = ("lighting", "lighting_static", "lighting_led_matrix")
ZONE_CAPS = ("lighting", "lighting_static")
KBD = "KBD0001"
PAD = "PAD0001"
MOUSE = "MOUSE0001"
RED = (255, 0, 0)
BLUE = (0, 0, 255)
BLACK = (0, 0, 0)
KEY_W = 17
KEY_W_CELL = (2, 3)
WASD = KeyGroup("WASD", ((2, 3), (3, 2), (3, 3), (3, 4)), KeyEffect(palette=(RED,)))
STATIC = AdvancedPreset("static", "Static", (
    DeviceProgram(KBD, (WASD,)), DeviceProgram(PAD, (KeyGroup("Esc", ((0, 1),),
                                                                KeyEffect(palette=(BLUE,))),)),
    DeviceProgram(MOUSE, (WASD,))))
REACTIVE = AdvancedPreset("reactive", "Reactive", (DeviceProgram(KBD, (
    KeyGroup("All", tuple((r, c) for r in range(6) for c in range(22)),
             KeyEffect(effect=EFFECT_REACTIVE, palette=(RED,), fade=1.0)),)),))


class Clock:
    """A settable clock."""

    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def devices(make_device):
    return [make_device(name="Razer Keyboard", serial=KBD, capabilities=MATRIX_CAPS),
            make_device(name="Razer Pad", serial=PAD, capabilities=MATRIX_CAPS),
            make_device(name="Razer Mouse", serial=MOUSE, capabilities=ZONE_CAPS)]


@pytest.fixture
def state():
    return lighting_state.LightingState()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def runtime(state, clock):
    rt = AdvancedRuntime(start_thread=False, clock=clock, rng=random.Random(1))
    state.add_claim_listener(rt.release)
    return rt


def _last(dev):
    return dev.fx.advanced.draws[-1]


def test_activate_paints_groups_and_black_elsewhere(runtime, devices):
    kbd, pad, _mouse = devices
    assert runtime.activate(STATIC, devices) == [KBD, PAD]
    assert runtime.active_key() == "static"
    runtime.step()
    frame = _last(kbd)
    assert len(frame) == 6 * 22
    assert all(frame[cell] == RED for cell in WASD.leds)
    assert frame[(0, 0)] == BLACK and frame[(5, 21)] == BLACK
    assert _last(pad)[(0, 1)] == BLUE and _last(pad)[(2, 3)] == BLACK


def test_static_only_paints_once_until_update(runtime, devices):
    kbd = devices[0]
    runtime.activate(STATIC, devices)
    runtime.step()
    runtime.step()
    assert len(kbd.fx.advanced.draws) == 1
    assert runtime.update(STATIC.with_changes(label="Changed"))
    runtime.step()
    assert len(kbd.fx.advanced.draws) == 2
    assert not runtime.update(REACTIVE)


def test_release_restores_only_released(runtime, devices):
    kbd, pad, _ = devices
    runtime.activate(STATIC, devices)
    runtime.release([PAD])
    assert pad.fx.advanced.restore_calls == 1
    assert kbd.fx.advanced.restore_calls == 0
    assert runtime.active_serials() == [KBD]
    runtime.release([KBD])
    assert runtime.active_key() is None


def test_release_remembers_claimed_away_until_explicit_activate(runtime, devices):
    runtime.activate(STATIC, devices)
    runtime.release([PAD, "NOT-SHOWN"])
    assert runtime.claimed_away() == frozenset({PAD})
    runtime.refresh([])
    runtime.activate(STATIC, devices, reclaim=False)  # an automatic restore keeps it
    assert runtime.claimed_away() == frozenset({PAD})
    runtime.activate(STATIC, devices)  # the page's Activate takes everything back
    assert runtime.claimed_away() == frozenset()
    runtime.release([KBD])
    runtime.stop()
    assert runtime.claimed_away() == frozenset()


def test_emptied_listener_fires_only_when_release_empties(runtime, devices, caplog):
    emptied = []

    def boom(key):
        raise RuntimeError(key)

    runtime.add_emptied_listener(boom)
    runtime.add_emptied_listener(emptied.append)
    runtime.activate(STATIC, devices)
    runtime.release([KBD])
    assert emptied == []
    runtime.release([PAD])
    assert emptied == ["static"]
    assert "emptied listener failed" in caplog.text
    runtime.release([KBD, PAD])  # already empty
    runtime.activate(STATIC, devices)
    runtime.refresh([])  # a disconnect does not count
    runtime.release([KBD])
    assert emptied == ["static"]


def test_change_listener_fires_when_state_changes(runtime, devices, caplog):
    changes = []

    def boom():
        raise RuntimeError("listener broke")

    runtime.add_change_listener(boom)
    runtime.add_change_listener(lambda: changes.append(runtime.active_key()))
    runtime.activate(STATIC, devices)
    assert changes == ["static"]
    assert "change listener failed" in caplog.text
    assert runtime.update(STATIC)
    assert changes == ["static"] * 2
    assert not runtime.update(REACTIVE)  # not the active preset
    runtime.release([MOUSE])  # not shown: no change
    assert len(changes) == 2
    runtime.release([KBD])
    assert changes == ["static"] * 3
    runtime.refresh(devices)  # same devices: no change
    assert len(changes) == 3
    runtime.refresh([])
    assert changes[-1] is None and len(changes) == 4
    runtime.stop()  # already empty
    assert len(changes) == 4
    runtime.activate(STATIC, devices)
    runtime.stop()
    assert changes[-2:] == ["static", None]


def test_claim_from_lighting_state_releases(runtime, state, devices):
    kbd, pad, _ = devices
    runtime.activate(STATIC, devices)
    state.claim([KBD])
    assert kbd.fx.advanced.restore_calls == 1
    assert runtime.active_serials() == [PAD]


def test_presses_light_the_right_key(runtime, devices, clock):
    kbd = devices[0]
    runtime.activate(REACTIVE, devices)
    assert runtime.needs_key_events()
    runtime.feed_presses({"Razer Keyboard": KBD}, [[KEY_W, 1, 5], [240, 2, 6]])
    runtime.step()
    frame = _last(kbd)
    assert frame[KEY_W_CELL] == RED
    assert [cell for cell, colour in frame.items() if colour != BLACK] == [KEY_W_CELL]
    clock.now += 2.0
    runtime.step()
    assert _last(kbd)[KEY_W_CELL] == BLACK
    assert runtime._presses[KBD] == []


def test_update_ignores_invalid_preset(runtime, devices):
    runtime.activate(STATIC, devices)
    broken = STATIC.with_changes(programs=(DeviceProgram(KBD), DeviceProgram(KBD)))
    assert not runtime.update(broken)
    assert runtime._preset is STATIC
    edited = STATIC.with_changes(label="Edited")
    assert runtime.update(edited)
    assert runtime._preset is edited


def test_needs_key_events_false_for_static(runtime, devices):
    assert not runtime.needs_key_events()
    runtime.activate(STATIC, devices)
    assert not runtime.needs_key_events()


def test_stop_restores(runtime, devices):
    kbd, pad, _ = devices
    runtime.activate(STATIC, devices)
    runtime.stop()
    assert kbd.fx.advanced.restore_calls == 1 and pad.fx.advanced.restore_calls == 1
    assert runtime.active_key() is None
    runtime.step()
    assert kbd.fx.advanced.draws == []


def test_activate_replacement_restores_unused_devices(runtime, devices):
    kbd, pad, _ = devices
    runtime.activate(STATIC, devices)
    runtime.activate(REACTIVE, devices)
    assert pad.fx.advanced.restore_calls == 1
    assert kbd.fx.advanced.restore_calls == 0
    assert runtime.active_key() == "reactive"


def test_refresh_drops_gone_devices(runtime, devices):
    runtime.activate(STATIC, devices)
    runtime.refresh(devices[:1])
    assert runtime.active_serials() == [KBD]
    runtime.refresh([])
    assert runtime.active_key() is None


def test_shutdown_with_thread(devices):
    rt = AdvancedRuntime(fps=100)
    rt.activate(STATIC, devices)
    rt.shutdown()
    assert rt.active_key() is None
    assert devices[0].fx.advanced.restore_calls == 1


def test_shared_runtime_listens_to_claims(monkeypatch, state, devices):
    monkeypatch.setattr(advanced_runtime, "_shared", None)
    monkeypatch.setattr(lighting_state, "shared_lighting_state", lambda: state)
    shared = advanced_runtime.shared_runtime()
    assert shared is advanced_runtime.shared_runtime()
    shared._start_thread = False
    shared.activate(STATIC, devices)
    state.claim([KBD])
    assert shared.active_serials() == [PAD]
    shared.stop()
