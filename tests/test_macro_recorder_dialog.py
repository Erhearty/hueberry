# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the recorder dialog (fake engine, deferred worker)."""

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QDialog

from hueberry.ui import worker
from hueberry.ui.macro_recorder import NO_KEY_TEXT, RecorderDialog, strip_stop_key

IDENTITY = "1532:0084:Test Mouse:usb-1"


class FakeEngine:
    def __init__(self, events=None):
        self.calls = []
        self.events = events or []

    def record_start(self, identity):
        self.calls.append(("record_start", identity))
        return {}

    def record_stop(self):
        self.calls.append(("record_stop",))
        return {"events": list(self.events)}


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


KEY_A_EVENTS = [["KEY_A", 1, 0.0], ["KEY_A", 0, 0.1]]
PAUSE_EVENTS = [["KEY_PAUSE", 1, 0.2], ["KEY_PAUSE", 2, 0.3], ["KEY_PAUSE", 0, 0.4]]


def _recording(qtbot, pending, engine, capture=False):
    dialog = RecorderDialog(engine, IDENTITY, capture=capture)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.start()
    _finish(pending)
    assert dialog._recording
    return dialog


def test_pause_key_stops_and_accepts(qtbot, pending):
    engine = FakeEngine(KEY_A_EVENTS + PAUSE_EVENTS)
    dialog = _recording(qtbot, pending, engine)
    assert dialog.focusWidget() is dialog.status_label
    QTest.keyClick(dialog.focusWidget(), Qt.Key.Key_Pause)
    _finish(pending)
    assert engine.calls == [("record_start", IDENTITY), ("record_stop",)]
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.steps
    assert "KEY_A" in repr(dialog.steps) and "KEY_PAUSE" not in repr(dialog.steps)


def test_trailing_pause_not_in_steps(qtbot, pending):
    dialog = _recording(qtbot, pending, FakeEngine(KEY_A_EVENTS + PAUSE_EVENTS))
    dialog.stop_button.click()
    _finish(pending)
    assert "KEY_PAUSE" not in repr(dialog.steps)
    assert dialog.steps


def test_capture_only_pause_is_nothing(qtbot, pending):
    dialog = _recording(qtbot, pending, FakeEngine(PAUSE_EVENTS), capture=True)
    assert dialog.focusWidget() is dialog.status_label
    QTest.keyClick(dialog.focusWidget(), Qt.Key.Key_Pause)
    _finish(pending)
    assert dialog.captured is None
    assert dialog.status_label.text() == NO_KEY_TEXT
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.isVisible()


def test_second_pause_while_stopping_is_ignored(qtbot, pending):
    engine = FakeEngine(KEY_A_EVENTS + PAUSE_EVENTS)
    dialog = _recording(qtbot, pending, engine)
    focused = dialog.focusWidget()
    QTest.keyClick(focused, Qt.Key.Key_Pause)
    assert dialog._recording  # record_stop reply still deferred
    QTest.keyClick(focused, Qt.Key.Key_Pause)
    assert len(pending) == 1  # only one record_stop queued
    _finish(pending)
    assert engine.calls == [("record_start", IDENTITY), ("record_stop",)]
    assert pending == []
    assert dialog.result() == QDialog.DialogCode.Accepted


@pytest.mark.parametrize("key", [Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter])
def test_space_and_enter_do_not_stop(qtbot, pending, key):
    engine = FakeEngine(KEY_A_EVENTS)
    dialog = _recording(qtbot, pending, engine)
    focused = dialog.focusWidget()
    assert focused is dialog.status_label
    assert focused is not dialog.stop_button
    QTest.keyClick(focused, key)
    assert engine.calls == [("record_start", IDENTITY)]
    assert pending == []
    assert dialog._recording
    assert dialog.isVisible()
    assert dialog.result() == 0  # neither accepted nor rejected


def test_pause_while_idle_does_nothing(qtbot, pending):
    engine = FakeEngine(KEY_A_EVENTS)
    dialog = RecorderDialog(engine, IDENTITY)
    qtbot.addWidget(dialog)
    QTest.keyClick(dialog, Qt.Key.Key_Pause)
    assert engine.calls == [] and pending == []
    assert dialog.start_button.isEnabled()


def test_strip_stop_key():
    middle = [["KEY_A", 1, 0.0], ["KEY_PAUSE", 1, 0.1], ["KEY_PAUSE", 0, 0.2], ["KEY_A", 0, 0.3]]
    assert strip_stop_key(middle + PAUSE_EVENTS) == middle
    assert strip_stop_key(PAUSE_EVENTS) == []
    assert strip_stop_key([]) == []
    assert strip_stop_key(KEY_A_EVENTS) == KEY_A_EVENTS
