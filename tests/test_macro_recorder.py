# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the macro recorder."""

import json

from fake_evdev import make_event

from hueberry.macro_engine.recorder import MAX_RECORDED_EVENTS, Recorder
from hueberry.macros import keycodes

EV_SYN, EV_KEY, EV_REL = 0, 1, 2


def test_records_key_presses_and_releases(fake_evdev):
    """EV_KEY press/release are kept with names and relative times."""
    recorder = Recorder("id")
    recorder.handle(make_event(EV_KEY, 30, 1, 100.5))
    recorder.handle(make_event(EV_SYN, 0, 0, 100.5))
    recorder.handle(make_event(EV_REL, 0, 5, 100.6))
    recorder.handle(make_event(EV_KEY, 30, 0, 100.75))
    recorder.handle(make_event(EV_KEY, 0x110, 1, 101.0))
    events = recorder.stop()
    assert events == [["KEY_A", 1, 0.0], ["KEY_A", 0, 0.25], ["BTN_LEFT", 1, 0.5]]
    assert json.loads(json.dumps(events)) == events
    assert keycodes.events_to_steps(events)


def test_repeats_and_unknown_codes_are_ignored(fake_evdev):
    """Auto-repeat (value 2) and codes without a name are skipped."""
    recorder = Recorder("id")
    recorder.handle(make_event(EV_KEY, 30, 2, 1.0))
    recorder.handle(make_event(EV_KEY, 0x2FE, 1, 1.0))
    assert recorder.stop() == [] and recorder.count == 0


def test_cap_limits_recording(fake_evdev):
    """No more than max_events are stored; truncated is flagged."""
    recorder = Recorder("id", max_events=3)
    for index in range(5):
        recorder.handle(make_event(EV_KEY, 30, index % 2, index))
    assert recorder.count == 3 and recorder.truncated
    assert MAX_RECORDED_EVENTS * 2 <= 500
