# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the Effects page wiring: key event poller, restore_last and PresetForgetter."""

import logging
import threading
from types import SimpleNamespace

import pytest

from hueberry.backend import advanced_preset_store, advanced_runtime
from hueberry.backend.advanced_presets import AdvancedPreset, DeviceProgram
from hueberry.backend.advanced_runtime import AdvancedRuntime
from hueberry.settings import LAST_ADVANCED_PRESET, Settings
from hueberry.ui import effects_wiring, worker

KBD = "KBD0001"
PAD = "PAD0001"
OTHER = "MOUSE0001"
NAME = "Razer BlackWidow"
PRESET = AdvancedPreset("mine", "Mine", (DeviceProgram(KBD), DeviceProgram(PAD)))
KEYBOARD = SimpleNamespace(serial=KBD)
KEYPAD = SimpleNamespace(serial=PAD)
MOUSE = SimpleNamespace(serial=OTHER)
MATRIX_CAPS = ("lighting", "lighting_static", "lighting_led_matrix")


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
    def __init__(self):
        self.needs = False
        self.key = None
        self.fed = []
        self.activated = []
        self.refreshed = 0
        self.claimed = frozenset()
        self.reclaims = []

    def needs_key_events(self):
        return self.needs

    def active_serials(self):
        return [KBD]

    def active_key(self):
        return self.key

    def feed_presses(self, names, events):
        self.fed.append((names, events))

    def claimed_away(self):
        return self.claimed

    def activate(self, preset, devices, *, reclaim=True):
        serials = [dev.serial for dev in devices]
        self.activated.append((preset.key, serials))
        self.reclaims.append(reclaim)
        self.key = preset.key
        return serials

    def refresh(self, devices):
        self.refreshed += 1


class FakeEngine:
    def __init__(self, fail=False):
        self.watched = []
        self.fail = fail
        self.fail_events = False
        self.next = None  # overrides the reply's cursor (an engine restart)

    def key_watch(self, names):
        if self.fail:
            raise OSError("engine gone")
        self.watched.append(names)
        return {"names": names, "nodes": []}

    def key_events(self, since):
        if self.fail or self.fail_events:
            raise OSError("engine gone")
        cursor = self.next if self.next is not None else since + 1
        return {"events": [[17, since, 5]], "next": cursor}


@pytest.fixture
def runtime(monkeypatch):
    fake = FakeRuntime()
    monkeypatch.setattr(advanced_runtime, "shared_runtime", lambda: fake)
    monkeypatch.setattr(worker, "run_async", _run_sync)
    return fake


@pytest.fixture
def real(monkeypatch, make_device):
    """A passive real runtime as the shared one, with a keyboard and a keypad."""
    rt = AdvancedRuntime(start_thread=False)
    monkeypatch.setattr(advanced_runtime, "shared_runtime", lambda: rt)
    devices = [make_device(name=NAME, serial=KBD, capabilities=MATRIX_CAPS),
               make_device(name="Razer Keypad", serial=PAD, capabilities=MATRIX_CAPS)]
    return SimpleNamespace(runtime=rt, devices=devices)


def _poller(qtbot, engine):
    poller = effects_wiring.KeyEventPoller(engine, lambda: {NAME: KBD})
    return poller


def _remember(key=PRESET.key):
    advanced_preset_store.save([PRESET])
    settings = Settings()
    settings.set(LAST_ADVANCED_PRESET, key)
    return settings


def test_poller_follows_needs_key_events(qtbot, runtime):
    engine = FakeEngine()
    poller = _poller(qtbot, engine)
    assert effects_wiring.POLL_INTERVAL_MS == 1000 // 30
    poller.sync()
    assert not poller.is_polling()
    runtime.needs = True
    poller.sync()
    assert poller.is_polling()
    assert engine.watched == [[NAME]]
    poller.poll()  # the first reply only sets the cursor (stale presses)
    poller.poll()
    poller.poll()
    assert runtime.fed == [({NAME: KBD}, [[17, 1, 5]]), ({NAME: KBD}, [[17, 2, 5]])]
    runtime.needs = False
    poller.sync()
    assert not poller.is_polling()
    assert engine.watched[-1] == []


def test_poller_tolerates_engine_errors_and_absence(qtbot, runtime):
    runtime.needs = True
    poller = _poller(qtbot, FakeEngine(fail=True))
    poller.sync()
    poller.poll()
    poller.poll()  # a failed request does not leave the poller stuck
    assert runtime.fed == []
    absent = _poller(qtbot, None)
    absent.sync()
    absent.poll()
    assert not absent.is_polling()


def test_failed_watch_is_sent_again(qtbot, runtime):
    runtime.needs = True
    engine = FakeEngine(fail=True)
    poller = _poller(qtbot, engine)
    poller.sync()
    assert not poller.is_polling()
    engine.fail = False
    poller.sync()
    assert engine.watched == [[NAME]]
    assert poller.is_polling()


def test_failed_events_back_off_and_log_once(qtbot, runtime, caplog):
    runtime.needs = True
    engine = FakeEngine()
    poller = _poller(qtbot, engine)
    poller.sync()
    engine.fail_events = True
    with caplog.at_level(logging.WARNING, logger=effects_wiring.__name__):
        poller.poll()
        assert not poller.is_polling()  # paused until the next sync tick
        poller.sync()
        poller.poll()
    assert engine.watched == [[NAME], [NAME]]  # the watch is sent again
    assert len([r for r in caplog.records if "Key events" in r.getMessage()]) == 1
    engine.fail_events = False
    poller.sync()
    poller.poll()
    poller.poll()
    assert runtime.fed == [({NAME: KBD}, [[17, 1, 5]])]


def test_engine_restart_watches_again(qtbot, runtime):
    runtime.needs = True
    engine = FakeEngine()
    poller = _poller(qtbot, engine)
    poller.sync()
    poller.poll()
    poller.poll()
    assert len(runtime.fed) == 1
    engine.next = 0  # the cursor went backwards: the engine restarted
    poller.poll()
    assert len(runtime.fed) == 1  # presses of the restart reply are not fed
    assert not poller.is_polling()
    poller.sync()
    assert engine.watched == [[NAME], [NAME]]
    engine.next = None
    poller.poll()  # fresh watch: cursor only
    poller.poll()
    assert runtime.fed[-1] == ({NAME: KBD}, [[17, 1, 5]])


def test_release_watch_stops_engine_watch(qtbot, runtime):
    runtime.needs = True
    engine = FakeEngine()
    poller = _poller(qtbot, engine)
    poller.release_watch()  # not watching: nothing sent
    assert engine.watched == []
    poller.sync()
    poller.release_watch()
    assert engine.watched == [[NAME], []]
    assert not poller.is_polling()
    failing = _poller(qtbot, engine)
    failing.sync()
    engine.fail = True
    failing.release_watch()  # never raises


def test_restore_last_refreshes_an_active_preset(runtime):
    settings = _remember()
    effects_wiring.restore_last([KEYBOARD], settings)
    effects_wiring.restore_last([KEYBOARD], settings)
    assert runtime.activated == [(PRESET.key, [KBD])]
    assert runtime.reclaims == [False]  # a restore keeps claimed_away
    assert runtime.refreshed == 1


def test_restore_last_skips_claimed_away_devices(runtime):
    settings = _remember()
    runtime.claimed = frozenset({KBD})
    effects_wiring.restore_last([KEYBOARD, KEYPAD], settings)
    assert runtime.activated == [(PRESET.key, [PAD])]


def test_restore_last_waits_for_its_devices(runtime):
    settings = _remember()
    effects_wiring.restore_last([], settings)
    effects_wiring.restore_last([MOUSE], settings)
    assert runtime.activated == []
    effects_wiring.restore_last([MOUSE, KEYBOARD], settings)
    assert runtime.activated == [(PRESET.key, [KBD])]


def test_restore_last_all_claimed_does_not_activate(runtime):
    settings = _remember()
    runtime.claimed = frozenset({KBD, PAD})
    effects_wiring.restore_last([KEYBOARD, KEYPAD], settings)
    assert runtime.activated == []


def test_restore_last_after_reconnect_shows_preset_again(real):
    settings = _remember()
    effects_wiring.restore_last(real.devices, settings)
    assert real.runtime.active_serials() == [KBD, PAD]
    real.runtime.refresh([])  # the daemon went away: the reload has no devices
    effects_wiring.restore_last([], settings)
    assert real.runtime.active_key() is None
    effects_wiring.restore_last(real.devices, settings)  # reconnected
    assert real.runtime.active_key() == PRESET.key
    assert sorted(real.runtime.active_serials()) == [KBD, PAD]


def test_restore_last_does_not_retake_claimed_device_after_reconnect(real):
    settings = _remember()
    effects_wiring.restore_last(real.devices, settings)
    real.runtime.release([KBD])  # other lighting took the keyboard
    real.runtime.refresh([])
    effects_wiring.restore_last(real.devices, settings)
    assert real.runtime.active_serials() == [PAD]
    assert real.runtime.claimed_away() == frozenset({KBD})


def test_restore_last_forgets_missing_preset(runtime):
    settings = Settings()
    settings.set(LAST_ADVANCED_PRESET, "gone")
    effects_wiring.restore_last([], settings)
    assert runtime.activated == []
    assert Settings().last_advanced_preset == ""


def test_restore_last_without_setting_does_nothing(runtime):
    effects_wiring.restore_last([KEYBOARD], Settings())
    assert runtime.activated == []


def test_forgetter_clears_only_the_emptied_preset(qtbot):
    _remember()
    forgetter = effects_wiring.PresetForgetter()
    forgetter.on_emptied("another")  # the setting names a different preset
    assert Settings().last_advanced_preset == PRESET.key
    forgetter.on_emptied(PRESET.key)
    assert Settings().last_advanced_preset == ""


def test_forgetter_marshals_worker_thread_calls(qtbot):
    _remember()
    forgetter = effects_wiring.PresetForgetter()
    thread = threading.Thread(target=forgetter.on_emptied, args=(PRESET.key,))
    thread.start()
    thread.join()
    qtbot.waitUntil(lambda: Settings().last_advanced_preset == "")


def test_forgetter_follows_runtime_release_not_refresh(qtbot, real):
    settings = _remember()
    forgetter = effects_wiring.PresetForgetter()
    real.runtime.add_emptied_listener(forgetter.on_emptied)
    effects_wiring.restore_last(real.devices, settings)
    real.runtime.release([KBD])  # the pad still shows it
    assert Settings().last_advanced_preset == PRESET.key
    real.runtime.refresh([])  # a disconnect empties it: keep the preset
    real.runtime.release([KBD, PAD, OTHER])  # claims while already empty
    assert Settings().last_advanced_preset == PRESET.key
    effects_wiring.restore_last(real.devices, settings)  # the pad comes back
    real.runtime.release([PAD])
    assert Settings().last_advanced_preset == ""
