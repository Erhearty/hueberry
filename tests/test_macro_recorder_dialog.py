# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the recorder dialog (fake engine, deferred worker)."""

import pytest

from hueberry.ui import worker
from hueberry.ui.macro_recorder import RecorderDialog

IDENTITY = "1532:0084:Test Mouse:usb-1"


class FakeEngine:
    def __init__(self):
        self.calls = []

    def record_start(self, identity):
        self.calls.append(("record_start", identity))
        return {}

    def record_stop(self):
        self.calls.append(("record_stop",))
        return {"events": []}


@pytest.fixture
def pending(monkeypatch):
    """run_async stand-in that queues tasks; the test completes them explicitly."""
    tasks = []
    monkeypatch.setattr(worker, "run_async",
                        lambda fn, on_done=None, on_error=None: tasks.append((fn, on_done)))
    return tasks


def _finish(tasks):
    fn, on_done = tasks.pop(0)
    result = fn()
    if on_done is not None:
        on_done(result)


def test_reject_while_starting_stops_recording(qtbot, pending):
    engine = FakeEngine()
    dialog = RecorderDialog(engine, IDENTITY)
    qtbot.addWidget(dialog)
    dialog.start()
    dialog.reject()
    assert pending and engine.calls == []  # record_start still in flight, nothing stopped yet
    _finish(pending)  # record_start answers after the dialog was closed
    assert not dialog._recording
    _finish(pending)
    assert engine.calls == [("record_start", IDENTITY), ("record_stop",)]
    assert pending == []


def test_start_then_record_normally(qtbot, pending):
    engine = FakeEngine()
    dialog = RecorderDialog(engine, IDENTITY)
    qtbot.addWidget(dialog)
    dialog.start()
    _finish(pending)
    assert dialog._recording
    assert dialog.stop_button.isEnabled()
    assert pending == []
