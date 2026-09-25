# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the macro editor and recorder dialogs (synchronous worker)."""

import pytest
from PyQt6.QtWidgets import QDialogButtonBox

from hueberry.macros import model
from hueberry.macros.model import DelayStep, KeyStep, Macro
from hueberry.macros.protocol import EngineError
from hueberry.ui import worker
from hueberry.ui.macro_editor import MacroEditorDialog, StepDialog, describe_step
from hueberry.ui.macro_recorder import RecorderDialog, first_pressed

IDENTITY = "1532:0084:Test Mouse:usb-1"


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


class FakeEngine:
    def __init__(self, events=(), start_error=None):
        self.events = [list(event) for event in events]
        self.start_error = start_error
        self.calls = []

    def record_start(self, identity):
        self.calls.append(("record_start", identity))
        if self.start_error is not None:
            raise self.start_error
        return {"identity": identity}

    def record_stop(self):
        self.calls.append(("record_stop",))
        return {"identity": IDENTITY, "events": self.events, "truncated": False}


@pytest.fixture(autouse=True)
def sync_worker(monkeypatch):
    monkeypatch.setattr(worker, "run_async", _run_sync)


def _macro(steps=None, trigger="BTN_SIDE"):
    return Macro(id="m1", name="Copy", enabled=True, trigger=trigger,
                 steps=steps if steps is not None else [KeyStep("KEY_A")])


def _editor(qtbot, macro=None, **kwargs):
    editor = MacroEditorDialog(macro or _macro(), **kwargs)
    qtbot.addWidget(editor)
    return editor


def _texts(editor):
    return [editor.steps_list.item(row).text() for row in range(editor.steps_list.count())]


def _ok(dialog):
    return dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)


def test_describe_step():
    assert describe_step(KeyStep("KEY_A")) == "Tap A"
    assert describe_step(KeyStep("BTN_SIDE", model.ACTION_PRESS)) == "Press Button Side"
    assert describe_step(DelayStep(50)) == "Wait 50 ms"


def test_add_key_and_delay_steps(qtbot):
    editor = _editor(qtbot)
    editor.add_key_button.click()
    dialog = editor.step_dialog
    dialog.code_combo.setCurrentText("KEY_B")
    dialog.action_combo.setCurrentIndex(dialog.action_combo.findData(model.ACTION_PRESS))
    dialog.accept()
    editor.add_delay_button.click()
    editor.step_dialog.delay_spin.setValue(120)
    editor.step_dialog.accept()
    assert editor.steps() == [KeyStep("KEY_A"), KeyStep("KEY_B", model.ACTION_PRESS), DelayStep(120)]
    assert _texts(editor) == ["Tap A", "Press B", "Wait 120 ms"]


def test_edit_step(qtbot):
    editor = _editor(qtbot)
    editor.steps_list.setCurrentRow(0)
    editor.edit_button.click()
    dialog = editor.step_dialog
    dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData("delay"))
    assert not dialog.code_combo.isEnabled()
    dialog.delay_spin.setValue(10)
    dialog.accept()
    assert editor.steps() == [DelayStep(10)]


def test_reorder_and_delete(qtbot):
    editor = _editor(qtbot, _macro([KeyStep("KEY_A"), KeyStep("KEY_B"), DelayStep(5)]))
    editor.steps_list.setCurrentRow(2)
    assert not editor.down_button.isEnabled()
    editor.up_button.click()
    assert _texts(editor) == ["Tap A", "Wait 5 ms", "Tap B"]
    assert editor.steps_list.currentRow() == 1
    editor.steps_list.setCurrentRow(0)
    editor.down_button.click()
    assert _texts(editor) == ["Wait 5 ms", "Tap A", "Tap B"]
    editor.delete_button.click()
    assert _texts(editor) == ["Wait 5 ms", "Tap B"]
    assert editor.steps_list.currentRow() == 1


def test_delay_bounds(qtbot):
    dialog = StepDialog(DelayStep(20))
    qtbot.addWidget(dialog)
    dialog.delay_spin.setValue(model.MAX_DELAY_MS + 5000)
    assert dialog.step() == DelayStep(model.MAX_DELAY_MS)
    dialog.delay_spin.setValue(-5)
    assert dialog.step() == DelayStep(model.MIN_DELAY_MS)


def test_validation_message(qtbot):
    editor = _editor(qtbot, taken_triggers={"BTN_EXTRA"})
    assert _ok(editor).isEnabled()
    editor.trigger_combo.setCurrentText("NOT_A_KEY")
    assert not _ok(editor).isEnabled()
    assert "unknown trigger" in editor.validation_label.text()
    editor.trigger_combo.setCurrentText("BTN_EXTRA")
    assert "already triggers another macro" in editor.validation_label.text()
    editor.trigger_combo.setCurrentText("BTN_SIDE")
    editor.steps_list.setCurrentRow(0)
    editor.delete_button.click()
    assert "at least one step" in editor.validation_label.text()
    assert not _ok(editor).isEnabled()


def test_recording_needs_engine(qtbot):
    editor = _editor(qtbot)
    assert not editor.record_button.isEnabled()
    assert not editor.capture_button.isEnabled()


def test_capture_trigger(qtbot):
    engine = FakeEngine([["BTN_EXTRA", 1, 0.0], ["BTN_EXTRA", 0, 0.1]])
    editor = _editor(qtbot, engine=engine, identity=IDENTITY)
    editor.capture_button.click()
    recorder = editor.recorder
    recorder.start_button.click()
    assert recorder.stop_button.isEnabled()
    recorder.stop_button.click()
    assert editor.trigger_combo.currentText() == "BTN_EXTRA"
    assert engine.calls == [("record_start", IDENTITY), ("record_stop",)]


def test_recorded_steps_inserted_after_selection(qtbot):
    engine = FakeEngine([["KEY_B", 1, 0.0], ["KEY_B", 0, 0.05], ["KEY_C", 1, 0.051]])
    editor = _editor(qtbot, _macro([KeyStep("KEY_A"), KeyStep("KEY_Z")]), engine=engine,
                     identity=IDENTITY)
    editor.steps_list.setCurrentRow(0)
    editor.record_button.click()
    editor.recorder.start_button.click()
    editor.recorder.stop_button.click()
    assert editor.steps() == [
        KeyStep("KEY_A"), KeyStep("KEY_B", model.ACTION_PRESS), DelayStep(50),
        KeyStep("KEY_B", model.ACTION_RELEASE), KeyStep("KEY_C", model.ACTION_PRESS),
        KeyStep("KEY_Z"),
    ]


def test_empty_recording_keeps_dialog_open(qtbot):
    recorder = RecorderDialog(FakeEngine(), IDENTITY)
    qtbot.addWidget(recorder)
    recorder.start_button.click()
    recorder.stop_button.click()
    assert recorder.result() == 0
    assert "Nothing was recorded" in recorder.status_label.text()
    assert recorder.start_button.isEnabled()


def test_recorder_start_failure(qtbot):
    recorder = RecorderDialog(FakeEngine(start_error=EngineError("already recording")), IDENTITY)
    qtbot.addWidget(recorder)
    recorder.start_button.click()
    assert "already recording" in recorder.status_label.text()
    assert recorder.start_button.isEnabled()
    assert not recorder.stop_button.isEnabled()


def test_cancel_while_recording_stops_engine(qtbot):
    engine = FakeEngine()
    recorder = RecorderDialog(engine, IDENTITY)
    qtbot.addWidget(recorder)
    recorder.start_button.click()
    recorder.reject()
    assert engine.calls[-1] == ("record_stop",)


def test_first_pressed_skips_releases_and_invalid():
    assert first_pressed([["KEY_A", 0, 0.0], ["BOGUS", 1, 0.1], ["KEY_B", 1, 0.2]]) == "KEY_B"
    assert first_pressed([]) is None
