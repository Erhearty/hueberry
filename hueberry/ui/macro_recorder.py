# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Dialog that records key/button events of one device through the macro engine.

The engine (not Qt) does the recording, so side buttons and keys of any
device are seen even on Wayland. In capture mode the first pressed key or
button becomes :attr:`RecorderDialog.captured` (used to pick a trigger);
otherwise the recording is turned into steps (:attr:`RecorderDialog.steps`).
Engine calls go through ``worker.run_async`` so tests can make them synchronous.
A recording is finished with the Stop button or the Pause key; the trailing
Pause events themselves are not recorded. Space and Enter never stop it.
"""

import logging
from collections import deque
from typing import Any, Callable, Iterable

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from hueberry.macros import keycodes
from hueberry.ui import theme, worker

logger = logging.getLogger(__name__)

RECORD_TITLE = "Record macro"
CAPTURE_TITLE = "Capture trigger"
START_TEXT = "&Start recording"
STOP_TEXT = "S&top"
STOP_TOOLTIP = "Stop (Pause)"
IDLE_RECORD_TEXT = ("Press Start, perform the keys and buttons of the macro, "
                    "then press Stop or the Pause key.")
IDLE_CAPTURE_TEXT = ("Press Start, press the key or button that should trigger the macro, "
                     "then press Stop or the Pause key.")
STARTING_TEXT = "Starting\u2026"
RECORDING_TEXT = "Recording\u2026 press Stop or the Pause key when done."
STOPPING_TEXT = "Stopping\u2026"
NOTHING_RECORDED_TEXT = "Nothing was recorded; try again."
NO_KEY_TEXT = "No key or button was pressed; try again."
TRUNCATED_TEXT = "The recording was cut off at the size limit."
EVENT_CODE, EVENT_VALUE = 0, 1
STOP_KEY = Qt.Key.Key_Pause  # Qt key that stops a running recording
STOP_KEY_CODE = "KEY_PAUSE"  # the same key as recorded by the engine
CAPTURE_POLL_MS = 100  # how often a capture asks the engine for newly pressed keys


def first_pressed(events: list) -> str | None:
    """The first valid key/button name pressed in ``[[code, value, t], ...]``."""
    for event in events:
        if len(event) > EVENT_VALUE and event[EVENT_VALUE] == keycodes.VALUE_PRESS:
            if keycodes.is_valid_code(event[EVENT_CODE]):
                return event[EVENT_CODE]
    return None


def first_watched(events: list) -> str | None:
    """The first valid key/button name among watched ``[[code, seq, t_ms], ...]`` key-downs."""
    for event in events:
        name = keycodes.name_for(event[EVENT_CODE]) if len(event) > EVENT_CODE else None
        if keycodes.is_valid_code(name):
            return name
    return None


def strip_stop_key(events: list) -> list:
    """Drop the trailing Pause events (press, repeat, release) that stopped the recording.

    Everything up to and including the last non-Pause event is kept, so a Pause
    in the middle of the recording stays.
    """
    end = len(events)
    while end and len(events[end - 1]) > EVENT_CODE and events[end - 1][EVENT_CODE] == STOP_KEY_CODE:
        end -= 1
    return list(events[:end])


class RecorderDialog(QDialog):
    """Start/Stop recording of ``identity``; accepted once something usable arrived."""

    def __init__(self, engine: Any, identity: str, *, capture: bool = False,
                 parent: QWidget | None = None, device_name: str | None = None,
                 also_identities: Iterable[str] = ()) -> None:
        super().__init__(parent)
        self._engine = engine
        self._identity = identity
        self._capture = capture
        self._also_identities = list(also_identities)  # further devices recorded beside identity
        self._device_name = device_name  # evdev name of the device; a capture watches its key-downs
        self._recording = False
        self._watching = False  # key_watch is on for this dialog
        self._poll_in_flight = False  # a key_events request is in flight
        self._since = 0  # key_events cursor
        self._previous_names: list[str] | None = None  # watched names before this capture; restored after it
        self._watch_ops: deque = deque()  # engine watch ops (start, restore) in order; one runs at a time
        self._watch_busy = False
        self._start_pending = False  # record_start is in flight
        self._cancelled = False  # rejected while record_start was in flight
        self.steps: list = []
        self.captured: str | None = None
        self.truncated = False
        self.setWindowTitle(CAPTURE_TITLE if capture else RECORD_TITLE)
        self.status_label = QLabel(IDLE_CAPTURE_TEXT if capture else IDLE_RECORD_TEXT, self)
        self.start_button = QPushButton(START_TEXT, self)
        theme.set_role(self.start_button, "primary")
        self.stop_button = QPushButton(STOP_TEXT, self)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, self)
        self._configure_widgets()
        self._build_layout()
        self.start_button.clicked.connect(self.start)
        self.stop_button.clicked.connect(self.stop)
        self.buttons.rejected.connect(self.reject)
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(CAPTURE_POLL_MS)
        self.poll_timer.timeout.connect(self._poll_capture)
        self._set_buttons(idle=True)

    def _configure_widgets(self) -> None:
        """Label and button settings; no button is (auto)default so Enter/Space never stop."""
        self.status_label.setWordWrap(True)
        self.status_label.setAccessibleName("Recording status")
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.status_label.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.stop_button.setToolTip(STOP_TOOLTIP)
        for button in (self.start_button, self.stop_button, *self.buttons.buttons()):
            button.setAutoDefault(False)
            button.setDefault(False)

    def _build_layout(self) -> None:
        row = QHBoxLayout()
        row.addWidget(self.start_button)
        row.addWidget(self.stop_button)
        row.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addWidget(self.status_label)
        layout.addLayout(row)
        layout.addWidget(self.buttons)

    def _set_buttons(self, idle: bool = False, recording: bool = False) -> None:
        self.start_button.setEnabled(idle)
        self.stop_button.setEnabled(recording)

    def _show(self, text: str) -> None:
        self.status_label.setText(text)

    def start(self) -> None:
        """Ask the engine to start recording."""
        self._set_buttons()
        self._show(STARTING_TEXT)
        self._start_pending = True
        identity, also = self._identity, self._also_identities
        worker.run_async(lambda: self._engine.record_start(identity, also_identities=also),
                         self._on_started, self._on_failed)

    def stop(self) -> None:
        """Ask the engine to stop and hand over the events."""
        self._set_buttons()
        self._show(STOPPING_TEXT)
        self._stop_watch()
        worker.run_async(self._engine.record_stop, self._on_stopped, self._on_failed)

    @worker.ignore_deleted
    def _on_started(self, _result: Any) -> None:
        self._start_pending = False
        if self._cancelled:  # the dialog was closed meanwhile: end the orphan recording
            worker.run_async(self._engine.record_stop)
            return
        self._recording = True
        self._set_buttons(recording=True)
        self._show(RECORDING_TEXT)
        self.status_label.setFocus()  # not a button: Space/Enter must not stop the recording
        if self._capture and self._device_name:
            self._begin_watch()

    @worker.ignore_deleted
    def _on_stopped(self, result: Any) -> None:
        self._recording = False
        events = result.get("events", []) if isinstance(result, dict) else []
        events = strip_stop_key(events)
        self.truncated = bool(isinstance(result, dict) and result.get("truncated"))
        if self._capture:
            self.captured = first_pressed(events)
            done, empty_text = self.captured is not None, NO_KEY_TEXT
        else:
            self.steps = keycodes.events_to_steps(events)
            done, empty_text = bool(self.steps), NOTHING_RECORDED_TEXT
        if done:
            self.accept()
            return
        self._set_buttons(idle=True)
        self._show(empty_text)

    @worker.ignore_deleted
    def _on_failed(self, message: str) -> None:
        logger.warning("Recording failed: %s", message)
        self._start_pending = False
        self._recording = False
        self._stop_watch()
        self._set_buttons(idle=True)
        self._show(f"Recording failed: {message}")

    # -- capture watch -------------------------------------------------------

    def _begin_watch(self) -> None:
        """Remember the watched names, watch key-downs of the device; the cursor starts after what is buffered."""
        name = self._device_name

        def watch_and_adopt() -> Any:
            self._previous_names = None
            self._previous_names = list(self._engine.key_watch_names())
            self._engine.key_watch([name])
            return self._engine.key_events(0)

        self._watching = True
        self._queue_watch(watch_and_adopt, self._on_watch_started, self._on_watch_failed)

    def _stop_watch(self) -> None:
        """Stop polling; the engine watches the names it had before the capture again (in the background)."""
        self.poll_timer.stop()
        if self._watching:
            self._watching = False
            self._queue_watch(self._restore_watch, None, self._on_restore_failed)

    def _restore_watch(self) -> Any:
        """Watch exactly the names read before the capture; nothing when they could not be read."""
        if self._previous_names is None:
            return None
        return self._engine.key_watch(self._previous_names)

    def _queue_watch(self, fn: Callable[[], Any], on_done: Callable[[Any], None] | None = None,
                     on_error: Callable[[str], None] | None = None) -> None:
        """Queue an engine watch op; ops run one after another so the last one queued is the final state."""
        self._watch_ops.append((fn, on_done, on_error))
        self._run_next_watch_op()

    def _run_next_watch_op(self) -> None:
        if self._watch_busy or not self._watch_ops:
            return
        fn, on_done, on_error = self._watch_ops.popleft()
        self._watch_busy = True
        worker.run_async(fn, lambda result: self._watch_op_done(on_done, result),
                         lambda message: self._watch_op_done(on_error, message))

    def _watch_op_done(self, callback: Callable[[Any], None] | None, arg: Any) -> None:
        self._watch_busy = False
        try:
            if callback is not None:
                callback(arg)
        finally:
            self._run_next_watch_op()

    def _on_restore_failed(self, message: str) -> None:
        logger.warning("Restoring the key watch failed: %s", message)

    @worker.ignore_deleted
    def _on_watch_started(self, result: Any) -> None:
        if not self._watching:  # stopped meanwhile
            return
        self._since = int(result.get("next", 0)) if isinstance(result, dict) else 0
        self.poll_timer.start()

    def _poll_capture(self) -> None:
        """Timer slot: ask for key-downs since the cursor (one request at a time)."""
        if self._poll_in_flight or not self._watching:
            return
        self._poll_in_flight = True
        since = self._since
        worker.run_async(lambda: self._engine.key_events(since), self._on_key_events,
                         self._on_watch_failed)

    @worker.ignore_deleted
    def _on_key_events(self, result: Any) -> None:
        self._poll_in_flight = False
        if not self._watching or not isinstance(result, dict):
            return
        self._since = int(result.get("next", self._since))
        name = first_watched(result.get("events", []))
        if name is not None:
            self._finish_capture(name)

    @worker.ignore_deleted
    def _on_watch_failed(self, message: str) -> None:
        """The watch is lost; the recording goes on and Stop or the Pause key still finishes it."""
        logger.warning("Watching key presses failed: %s", message)
        self._poll_in_flight = False
        self._stop_watch()
        if self._recording:
            self._show(f"Could not watch key presses: {message}. Press Stop or the Pause key when done.")

    def _finish_capture(self, name: str) -> None:
        """A key or button was pressed: keep it and end the recording (its events are not needed)."""
        self.captured = name
        self._stop_watch()
        if self._recording:
            self._recording = False
            worker.run_async(self._engine.record_stop)
        self.accept()

    def keyPressEvent(self, event: Any) -> None:
        """Stop a running recording on the Pause key; other keys get the default handling.

        Ignored while a stop is already pending (stop() disables the Stop button).
        """
        stoppable = self._recording and self.stop_button.isEnabled()
        if stoppable and event.key() == STOP_KEY and not event.isAutoRepeat():
            self.stop()
            event.accept()
            return
        super().keyPressEvent(event)

    def reject(self) -> None:
        """Cancel; a running recording is stopped in the background and discarded."""
        self._stop_watch()
        if self._recording:
            self._recording = False
            worker.run_async(self._engine.record_stop)
        elif self._start_pending:
            self._cancelled = True  # _on_started sends record_stop
        super().reject()
