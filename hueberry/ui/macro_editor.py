# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Dialogs editing one macro: name, trigger, enabled flag and its steps.

Sub-dialogs (step editor, recorder) are opened non-blocking with ``open()``
and kept as attributes, so tests can drive them without nested event loops.
"""

import logging
from typing import Any, Callable, Iterable

from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from hueberry.macros import keycodes, model
from hueberry.macros.model import DelayStep, KeyStep, Macro
from hueberry.ui import theme
from hueberry.ui.macro_recorder import RecorderDialog

logger = logging.getLogger(__name__)

EDITOR_TITLE = "Edit macro"
STEP_TITLE = "Macro step"
KIND_KEY = "key"
KIND_DELAY = "delay"
KIND_LABELS = ((KIND_KEY, "Key or button"), (KIND_DELAY, "Delay"))
ACTION_LABELS = ((model.ACTION_TAP, "Tap"), (model.ACTION_PRESS, "Press"),
                 (model.ACTION_RELEASE, "Release"))
DEFAULT_KEY = "KEY_A"
DEFAULT_DELAY_MS = 50
DELAY_SUFFIX = " ms"
NO_STEPS_TEXT = "Add at least one step."
TRIGGER_TAKEN_TEXT = "{} already triggers another macro of this device."
NO_ENGINE_TIP = "Needs the running macro engine"
VALID_TEXT = "Ready to save."


def describe_step(step: Any) -> str:
    """One-line label, e.g. ``Tap A`` or ``Wait 50 ms``."""
    if isinstance(step, DelayStep):
        return f"Wait {step.ms}{DELAY_SUFFIX}"
    action = dict(ACTION_LABELS).get(step.action, step.action)
    return f"{action} {keycodes.display_name(step.code)}"


def key_combo(parent: QWidget, current: str, accessible_name: str) -> QComboBox:
    """Editable combo of every key name (just ``current`` without evdev)."""
    combo = QComboBox(parent)
    combo.setEditable(True)
    names = keycodes.all_key_names()
    if current and current not in names:
        names = [current, *names]
    combo.addItems(names)
    combo.setCurrentText(current)
    combo.setAccessibleName(accessible_name)
    return combo


class StepDialog(QDialog):
    """Edits one key or delay step; the delay is bounded to MIN..MAX_DELAY_MS."""

    def __init__(self, step: Any = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(STEP_TITLE)
        step = step if step is not None else KeyStep(DEFAULT_KEY)
        self.kind_combo = QComboBox(self)
        for kind, label in KIND_LABELS:
            self.kind_combo.addItem(label, kind)
        is_key = isinstance(step, KeyStep)
        self.code_combo = key_combo(self, step.code if is_key else DEFAULT_KEY, "Key or button")
        self.action_combo = QComboBox(self)
        for action, label in ACTION_LABELS:
            self.action_combo.addItem(label, action)
        self.delay_spin = QSpinBox(self)
        self.delay_spin.setRange(model.MIN_DELAY_MS, model.MAX_DELAY_MS)
        self.delay_spin.setSuffix(DELAY_SUFFIX)
        self.delay_spin.setValue(step.ms if not is_key else DEFAULT_DELAY_MS)
        if is_key:
            self.action_combo.setCurrentIndex(max(0, self.action_combo.findData(step.action)))
        self.kind_combo.setCurrentIndex(0 if is_key else 1)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        self._build_layout()
        self.kind_combo.currentIndexChanged.connect(self._update_fields)
        self._update_fields()

    def _build_layout(self) -> None:
        form = QFormLayout()
        form.addRow("&Type:", self.kind_combo)
        form.addRow("&Key:", self.code_combo)
        form.addRow("&Action:", self.action_combo)
        form.addRow("&Delay:", self.delay_spin)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.buttons)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

    def _update_fields(self) -> None:
        is_key = self.kind_combo.currentData() == KIND_KEY
        self.code_combo.setEnabled(is_key)
        self.action_combo.setEnabled(is_key)
        self.delay_spin.setEnabled(not is_key)

    def step(self) -> Any:
        """The edited step."""
        if self.kind_combo.currentData() == KIND_DELAY:
            return DelayStep(self.delay_spin.value())
        return KeyStep(self.code_combo.currentText().strip(), self.action_combo.currentData())


class MacroEditorDialog(QDialog):
    """Edits a copy of ``macro``; :meth:`macro` returns the result once accepted.

    ``engine`` + ``identity`` enable recording and trigger capture;
    ``taken_triggers`` are triggers of the device's other macros.
    """

    def __init__(self, macro: Macro, *, engine: Any = None, identity: str | None = None,
                 taken_triggers: Iterable[str] = (), parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(EDITOR_TITLE)
        self._id = macro.id
        self._engine = engine
        self._identity = identity
        self._taken = set(taken_triggers)
        self._steps = list(macro.steps)
        self.step_dialog: StepDialog | None = None
        self.recorder: RecorderDialog | None = None
        self._build_fields(macro)
        self._build_step_buttons()
        self._build_layout()
        self._connect_signals()
        self._refresh_steps()

    # -- construction --------------------------------------------------------

    def _build_fields(self, macro: Macro) -> None:
        self.name_edit = QLineEdit(macro.name, self)
        self.name_edit.setMaxLength(model.MAX_NAME_LENGTH)
        self.enabled_check = QCheckBox("E&nabled", self)
        self.enabled_check.setChecked(macro.enabled)
        self.trigger_combo = key_combo(self, macro.trigger, "Trigger")
        self.capture_button = QPushButton("&Capture\u2026", self)
        self.steps_list = QListWidget(self)
        self.steps_list.setAccessibleName("Steps")
        self.validation_label = QLabel(self)
        self.validation_label.setWordWrap(True)
        self.validation_label.setAccessibleName("Validation")
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)

    def _build_step_buttons(self) -> None:
        labels = {"add_key": "Add &key\u2026", "add_delay": "Add &delay\u2026",
                  "edit": "&Edit\u2026", "up": "Move &up", "down": "Move do&wn",
                  "delete": "De&lete", "record": "&Record\u2026"}
        for key, text in labels.items():
            setattr(self, f"{key}_button", QPushButton(text, self))
        can_record = self._engine is not None and self._identity is not None
        for button in (self.record_button, self.capture_button):
            button.setEnabled(can_record)
            if not can_record:
                button.setToolTip(NO_ENGINE_TIP)

    def _build_layout(self) -> None:
        trigger_row = QHBoxLayout()
        trigger_row.addWidget(self.trigger_combo, 1)
        trigger_row.addWidget(self.capture_button)
        form = QFormLayout()
        form.addRow("&Name:", self.name_edit)
        form.addRow("&Trigger:", trigger_row)
        form.addRow("", self.enabled_check)
        side = QGridLayout()
        order = (self.add_key_button, self.add_delay_button, self.record_button, self.edit_button,
                 self.up_button, self.down_button, self.delete_button)
        for row, button in enumerate(order):
            side.addWidget(button, row, 0)
        side.setRowStretch(len(order), 1)
        steps = QHBoxLayout()
        steps.addWidget(self.steps_list, 1)
        steps.addLayout(side)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(steps, 1)
        layout.addWidget(self.validation_label)
        layout.addWidget(self.buttons)

    def _connect_signals(self) -> None:
        self.add_key_button.clicked.connect(lambda: self._open_step_dialog(KeyStep(DEFAULT_KEY), None))
        self.add_delay_button.clicked.connect(
            lambda: self._open_step_dialog(DelayStep(DEFAULT_DELAY_MS), None))
        self.edit_button.clicked.connect(self._edit_current)
        self.steps_list.itemActivated.connect(lambda _item: self._edit_current())
        self.up_button.clicked.connect(lambda: self._move_current(-1))
        self.down_button.clicked.connect(lambda: self._move_current(1))
        self.delete_button.clicked.connect(self._delete_current)
        self.record_button.clicked.connect(lambda: self._open_recorder(capture=False))
        self.capture_button.clicked.connect(lambda: self._open_recorder(capture=True))
        self.steps_list.currentRowChanged.connect(lambda _row: self._update_buttons())
        self.name_edit.textChanged.connect(lambda _text: self._validate())
        self.trigger_combo.currentTextChanged.connect(lambda _text: self._validate())
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

    # -- public API ----------------------------------------------------------

    def macro(self) -> Macro:
        """The macro as currently edited."""
        return Macro(id=self._id, name=self.name_edit.text().strip(),
                     enabled=self.enabled_check.isChecked(),
                     trigger=self.trigger_combo.currentText().strip(), steps=list(self._steps))

    def steps(self) -> list:
        """The current steps."""
        return list(self._steps)

    def problems(self) -> list[str]:
        """Why the macro cannot be saved yet ([] when it can)."""
        macro = self.macro()
        found = macro.problems()
        if not macro.steps:
            found.append(NO_STEPS_TEXT)
        if macro.trigger in self._taken:
            found.append(TRIGGER_TAKEN_TEXT.format(keycodes.display_name(macro.trigger)))
        return found

    # -- step editing --------------------------------------------------------

    def _insert_row(self) -> int:
        row = self.steps_list.currentRow()
        return row + 1 if row >= 0 else len(self._steps)

    def _insert(self, steps: list) -> None:
        room = model.MAX_STEPS - len(self._steps)
        row = self._insert_row()
        self._steps[row:row] = steps[:max(room, 0)]
        self._refresh_steps(row + len(steps[:max(room, 0)]) - 1)

    def _open_step_dialog(self, step: Any, row: int | None) -> None:
        self.step_dialog = StepDialog(step, self)
        self.step_dialog.accepted.connect(lambda dialog=self.step_dialog: self._step_done(dialog, row))
        self.step_dialog.open()

    def _step_done(self, dialog: StepDialog, row: int | None) -> None:
        if row is None:
            self._insert([dialog.step()])
            return
        self._steps[row] = dialog.step()
        self._refresh_steps(row)

    def _edit_current(self) -> None:
        row = self.steps_list.currentRow()
        if 0 <= row < len(self._steps):
            self._open_step_dialog(self._steps[row], row)

    def _move_current(self, offset: int) -> None:
        row = self.steps_list.currentRow()
        target = row + offset
        if row < 0 or not 0 <= target < len(self._steps):
            return
        self._steps[row], self._steps[target] = self._steps[target], self._steps[row]
        self._refresh_steps(target)

    def _delete_current(self) -> None:
        row = self.steps_list.currentRow()
        if 0 <= row < len(self._steps):
            del self._steps[row]
            self._refresh_steps(min(row, len(self._steps) - 1))

    def _open_recorder(self, capture: bool) -> None:
        self.recorder = RecorderDialog(self._engine, self._identity, capture=capture, parent=self)
        on_done: Callable[[RecorderDialog], None] = self._captured if capture else self._recorded
        self.recorder.accepted.connect(lambda dialog=self.recorder: on_done(dialog))
        self.recorder.open()

    def _recorded(self, dialog: RecorderDialog) -> None:
        self._insert(dialog.steps)

    def _captured(self, dialog: RecorderDialog) -> None:
        if dialog.captured is not None:
            self.trigger_combo.setCurrentText(dialog.captured)

    # -- state ---------------------------------------------------------------

    def _refresh_steps(self, select: int = -1) -> None:
        self.steps_list.clear()
        self.steps_list.addItems([describe_step(step) for step in self._steps])
        if 0 <= select < len(self._steps):
            self.steps_list.setCurrentRow(select)
        self._update_buttons()
        self._validate()

    def _update_buttons(self) -> None:
        row = self.steps_list.currentRow()
        has_row = 0 <= row < len(self._steps)
        self.edit_button.setEnabled(has_row)
        self.delete_button.setEnabled(has_row)
        self.up_button.setEnabled(has_row and row > 0)
        self.down_button.setEnabled(has_row and row < len(self._steps) - 1)
        full = len(self._steps) >= model.MAX_STEPS
        self.add_key_button.setEnabled(not full)
        self.add_delay_button.setEnabled(not full)

    def _validate(self) -> None:
        found = self.problems()
        self.validation_label.setText("\n".join(found) if found else VALID_TEXT)
        colour = theme.ERROR if found else theme.TEXT_MUTED
        self.validation_label.setStyleSheet(f"color: {colour};")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not found)
