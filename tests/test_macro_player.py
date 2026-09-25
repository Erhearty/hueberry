# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the macro player (deterministic: injected sleep and thread start)."""

import pytest

from hueberry.macro_engine.player import Player
from hueberry.macros.model import DelayStep, KeyStep

EV_SYN, EV_KEY = 0, 1
SYN = (EV_SYN, 0, 0)
KEY_A, KEY_B, KEY_LEFTCTRL = 30, 48, 29


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
    player = Player(uinput, sleep=sleeps.append, start_thread=threads)
    return player, uinput, sleeps, threads


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


def test_default_sleep_is_cancellable(fake_evdev):
    """Without an injected sleep, a stopped player's delays return immediately."""
    uinput = fake_evdev.UInput(name="clone")
    player = Player(uinput, start_thread=lambda target: None)
    player.stop()
    assert player._sleep(10_000) is True  # Event.wait returns at once once cancelled
    player.run([KeyStep("KEY_A")])
    assert uinput.writes == []
