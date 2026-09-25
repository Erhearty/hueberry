# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Dialog that records key/button events of one device through the macro engine.

The engine (not Qt) does the recording, so side buttons and keys of any
device are seen even on Wayland. In capture mode the first pressed key or
button becomes :attr:`RecorderDialog.captured` (used to pick a trigger);
otherwise the recording is turned into steps (:attr:`RecorderDialog.steps`).
Engine calls go through ``worker.run_async`` so tests can make them synchronous.
"""

import logging
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from hueberry.macros import keycodes
from hueberry.ui import worker

logger = logging.getLogger(__name__)

RECORD_TITLE = "Record macro"
CAPTURE_TITLE = "Capture trigger"
START_TEXT = "&Start recording"
STOP_TEXT = "S&top"
IDLE_RECORD_TEXT = "Press Start, perform the keys and buttons of the macro, then press Stop."
IDLE_CAPTURE_TEXT = "Press Start, press the key or button that should trigger the macro, then Stop."
STARTING_TEXT = "Starting\u2026"
RECORDING_TEXT = "Recording\u2026 press Stop when done."
STOPPING_TEXT = "Stopping\u2026"
NOTHING_RECORDED_TEXT = "Nothing was recorded; try again."
NO_KEY_TEXT = "No key or button was pressed; try again."
TRUNCATED_TEXT = "The recording was cut off at the size limit."
EVENT_CODE, EVENT_VALUE = 0, 1


def first_pressed(events: list) -> str | None:
    """The first valid key/button name pressed in ``[[code, value, t], ...]``."""
    for event in events:
        if len(event) > EVENT_VALUE and event[EVENT_VALUE] == keycodes.VALUE_PRESS:
            if keycodes.is_valid_code(event[EVENT_CODE]):
                return event[EVENT_CODE]
    return None


class RecorderDialog(QDialog):
    """Start/Stop recording of ``identity``; accepted once something usable arrived."""

    def __init__(self, engine: Any, identity: str, *, capture: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._identity = identity
        self._capture = capture
        self._recording = False
        self._start_pending = False  # record_start is in flight
        self._cancelled = False  # rejected while record_start was in flight
        self.steps: list = []
        self.captured: str | None = None
        self.truncated = False
        self.setWindowTitle(CAPTURE_TITLE if capture else RECORD_TITLE)
        self.status_label = QLabel(IDLE_CAPTURE_TEXT if capture else IDLE_RECORD_TEXT, self)
        self.status_label.setWordWrap(True)
        self.status_label.setAccessibleName("Recording status")
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.start_button = QPushButton(START_TEXT, self)
        self.stop_button = QPushButton(STOP_TEXT, self)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, self)
        self._build_layout()
        self.start_button.clicked.connect(self.start)
        self.stop_button.clicked.connect(self.stop)
        self.buttons.rejected.connect(self.reject)
        self._set_buttons(idle=True)

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
        worker.run_async(lambda: self._engine.record_start(self._identity),
                         self._on_started, self._on_failed)

    def stop(self) -> None:
        """Ask the engine to stop and hand over the events."""
        self._set_buttons()
        self._show(STOPPING_TEXT)
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
        self.stop_button.setFocus()

    @worker.ignore_deleted
    def _on_stopped(self, result: Any) -> None:
        self._recording = False
        events = result.get("events", []) if isinstance(result, dict) else []
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
        self._set_buttons(idle=True)
        self._show(f"Recording failed: {message}")

    def reject(self) -> None:
        """Cancel; a running recording is stopped in the background and discarded."""
        if self._recording:
            self._recording = False
            worker.run_async(self._engine.record_stop)
        elif self._start_pending:
            self._cancelled = True  # _on_started sends record_stop
        super().reject()
