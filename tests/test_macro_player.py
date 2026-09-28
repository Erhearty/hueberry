# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the macro player (deterministic: injected sleep and thread start)."""

import pytest

from hueberry.macro_engine.player import MIN_ITERATION_MS, Player
from hueberry.macros.model import AppActionStep, DelayStep, KeyStep

EV_SYN, EV_KEY = 0, 1
SYN = (EV_SYN, 0, 0)
KEY_A, KEY_B, KEY_LEFTCTRL = 30, 48, 29
TAP_A = [(EV_KEY, KEY_A, 1), SYN, (EV_KEY, KEY_A, 0), SYN]
GAP_S = MIN_ITERATION_MS / 1000


def _frozen_clock():
    return 0.0


class _Threads:
    """Captures worker targets instead of starting threads."""

    def __init__(self):
        self.targets = []

    def __call__(self, target):
        self.targets.append(target)

    def run_next(self):
        self.targets.pop(0)()


@pytest.fixture
def rig(fake_evdev):
    uinput = fake_evdev.UInput(name="clone")
    sleeps = []
    threads = _Threads()
    player = Player(uinput, sleep=sleeps.append, start_thread=threads, clock=_frozen_clock)
    return player, uinput, sleeps, threads


def _stopping_player(uinput, stop_after):
    """Synchronous player whose fake sleep calls stop() on its ``stop_after``-th call."""
    sleeps = []
    holder = {}

    def _sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == stop_after:
            holder["player"].stop()

    player = Player(uinput, sleep=_sleep, start_thread=lambda target: target(), clock=_frozen_clock)
    holder["player"] = player
    return player, sleeps


def test_tap_press_release_and_delay_sequence(rig):
    """tap = press,syn,release,syn; delays use the injected sleep in seconds."""
    player, uinput, sleeps, threads = rig
    assert player.play([KeyStep("KEY_A"), DelayStep(250), KeyStep("KEY_B", "press"),
                        KeyStep("KEY_B", "release")])
    assert uinput.writes == []
    threads.run_next()
    assert uinput.writes == [
        (EV_KEY, KEY_A, 1), SYN, (EV_KEY, KEY_A, 0), SYN,
        (EV_KEY, KEY_B, 1), SYN, (EV_KEY, KEY_B, 0), SYN,
    ]
    assert sleeps == [0.25]


def test_stuck_keys_are_released_at_end(rig):
    """Keys pressed but never released are released when the macro ends."""
    player, uinput, _sleeps, threads = rig
    player.play([KeyStep("KEY_LEFTCTRL", "press"), KeyStep("KEY_A", "press"), KeyStep("KEY_A", "release")])
    threads.run_next()
    assert uinput.writes[-2:] == [(EV_KEY, KEY_LEFTCTRL, 0), SYN]
    assert uinput.writes.count((EV_KEY, KEY_LEFTCTRL, 0)) == 1


def test_retrigger_while_playing_is_ignored(rig):
    """A second play() before the first finishes is ignored; afterwards it works."""
    player, _uinput, _sleeps, threads = rig
    assert player.play([KeyStep("KEY_A")])
    assert player.playing
    assert not player.play([KeyStep("KEY_B")])
    assert len(threads.targets) == 1
    threads.run_next()
    assert not player.playing
    assert player.play([KeyStep("KEY_B")])


def test_write_failure_ends_playback(rig):
    """A uinput error stops the macro without leaving it marked as playing."""
    player, uinput, _sleeps, threads = rig
    uinput.write_error = OSError("device gone")
    player.play([KeyStep("KEY_A"), KeyStep("KEY_B")])
    threads.run_next()
    assert not player.playing and uinput.writes == []


def test_stop_cancels_remaining_steps(fake_evdev):
    """stop() during a delay prevents the remaining steps (sleep is the cancel wait)."""
    uinput = fake_evdev.UInput(name="clone")
    holder = {}

    def _sleep(seconds):
        holder["player"].stop()

    player = Player(uinput, sleep=_sleep, start_thread=lambda target: target())
    holder["player"] = player
    player.play([KeyStep("KEY_A", "press"), DelayStep(5000), KeyStep("KEY_B")])
    assert uinput.writes == [(EV_KEY, KEY_A, 1), SYN, (EV_KEY, KEY_A, 0), SYN]


def test_n_iterations_repeat_the_steps(rig):
    """iterations=N emits the steps N times, with the minimum gap only between iterations."""
    player, uinput, sleeps, threads = rig
    assert player.play([KeyStep("KEY_A")], 3)
    threads.run_next()
    assert uinput.writes == TAP_A * 3
    assert sleeps == [GAP_S, GAP_S]
    assert not player.playing


def test_none_loops_until_stopped(fake_evdev):
    """iterations=None keeps looping until stop() (here from the third gap sleep)."""
    uinput = fake_evdev.UInput(name="clone")
    player, sleeps = _stopping_player(uinput, stop_after=3)
    assert player.play([KeyStep("KEY_A")], None)
    assert uinput.writes == TAP_A * 3
    assert len(sleeps) == 3 and not player.playing


def test_min_gap_only_sleeps_the_remainder(fake_evdev):
    """A fast iteration sleeps up to MIN_ITERATION_MS; a slow enough one does not sleep."""
    uinput = fake_evdev.UInput(name="clone")
    ticks = iter([0.0, 0.004, 1.0, 1.0 + 2 * GAP_S, 2.0])  # start, end, start, end, start
    sleeps = []
    player = Player(uinput, sleep=sleeps.append, start_thread=lambda target: target(),
                    clock=lambda: next(ticks))
    player.play([KeyStep("KEY_A")], 3)
    assert sleeps == [pytest.approx(GAP_S - 0.004)]
    assert uinput.writes == TAP_A * 3


def test_cancel_mid_loop_releases_held_keys(fake_evdev):
    """Stopping a loop inside a delay releases keys the macro still holds."""
    uinput = fake_evdev.UInput(name="clone")
    player, _sleeps = _stopping_player(uinput, stop_after=1)
    player.play([KeyStep("KEY_LEFTCTRL", "press"), DelayStep(100), KeyStep("KEY_A")], None)
    assert uinput.writes == [(EV_KEY, KEY_LEFTCTRL, 1), SYN, (EV_KEY, KEY_LEFTCTRL, 0), SYN]
    assert not player.playing


def test_current_is_set_while_playing(rig):
    """current holds the play() key while playing and is None when idle."""
    player, _uinput, _sleeps, threads = rig
    assert player.current is None
    player.play([KeyStep("KEY_A")], None, key="BTN_SIDE")
    assert player.current == "BTN_SIDE"
    player.stop()
    threads.run_next()
    assert player.current is None and not player.playing


def _rig_with_notify(fake_evdev, notify):
    uinput = fake_evdev.UInput(name="clone")
    player = Player(uinput, sleep=lambda seconds: None, start_thread=lambda target: target(),
                    clock=_frozen_clock, notify=notify)
    return player, uinput


def test_app_step_notifies_without_key_events(fake_evdev):
    """An app step calls notify with its action and writes nothing to uinput."""
    calls = []
    player, uinput = _rig_with_notify(fake_evdev, lambda action: calls.append(action) or True)
    player.play([AppActionStep("toggle-sysmon")])
    assert calls == ["toggle-sysmon"]
    assert uinput.writes == [] and not player.playing


@pytest.mark.parametrize("outcome", [False, RuntimeError("gui gone")])
def test_failing_notify_does_not_stop_the_macro(fake_evdev, outcome):
    """notify returning False or raising is logged; following key steps still play."""
    def _notify(action):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    player, uinput = _rig_with_notify(fake_evdev, _notify)
    player.play([AppActionStep("toggle-sysmon"), KeyStep("KEY_A")])
    assert uinput.writes == TAP_A and not player.playing


def test_default_sleep_is_cancellable(fake_evdev):
    """Without an injected sleep, a stopped player's delays return immediately."""
    uinput = fake_evdev.UInput(name="clone")
    player = Player(uinput, start_thread=lambda target: None)
    player.stop()
    assert player._sleep(10_000) is True  # Event.wait returns at once once cancelled
    player.run([KeyStep("KEY_A")])
    assert uinput.writes == []
