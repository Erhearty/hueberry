# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Dialogs editing one macro: name, trigger, enabled flag and its steps.

Sub-dialogs (step editor, recorder) are opened non-blocking with ``open()``
and kept as attributes, so tests can drive them without nested event loops.
"""

import logging
from typing import Any, Callable, Iterable

from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
    QWidget,
)

from hueberry import gui_link
from hueberry.macros import keycodes, model
from hueberry.macros.model import AppActionStep, DelayStep, KeyStep, Macro, WheelStep
from hueberry.ui import layouts, theme
from hueberry.ui.macro_recorder import RecorderDialog
from hueberry.ui.macro_repeat import RepeatModeGroup
from hueberry.ui.macro_review import ReviewDialog

logger = logging.getLogger(__name__)

EDITOR_TITLE = "Edit macro"
STEP_TITLE = "Macro step"
KIND_KEY = "key"
KIND_MOUSE = "mouse"
KIND_WHEEL = "wheel"
KIND_DELAY = "delay"
KIND_APP = "app"
KIND_LABELS = ((KIND_KEY, "Key or button"), (KIND_MOUSE, "Mouse button"), (KIND_WHEEL, "Mouse wheel"),
               (KIND_DELAY, "Delay"), (KIND_APP, "App action"))
STEP_KINDS = {KeyStep: KIND_KEY, DelayStep: KIND_DELAY, AppActionStep: KIND_APP, WheelStep: KIND_WHEEL}
WHEEL_LABELS = ((model.WHEEL_UP, "Up"), (model.WHEEL_DOWN, "Down"))
WHEEL_TEXT = {model.WHEEL_UP: "Scroll up", model.WHEEL_DOWN: "Scroll down"}
APP_STEP_PREFIX = "App: "
ACTION_LABELS = ((model.ACTION_TAP, "Tap"), (model.ACTION_PRESS, "Press"),
                 (model.ACTION_RELEASE, "Release"))
DEFAULT_KEY = "KEY_A"
DEFAULT_DELAY_MS = 50
DELAY_SUFFIX = " ms"
NO_STEPS_TEXT = "Add at least one step."
TRIGGER_TAKEN_TEXT = "{} already triggers another macro of this device."
NO_ENGINE_TIP = "Needs the running macro engine"
VALID_TEXT = "Ready to save."
DELETE_MANY_TEXT = "Delete the {} selected steps?"


def step_kind(step: Any) -> str:
    """Dialog kind of ``step``: a key step on a mouse button is a mouse-button step."""
    if isinstance(step, KeyStep) and step.code in keycodes.MOUSE_BUTTON_NAMES:
        return KIND_MOUSE
    return STEP_KINDS.get(type(step), KIND_KEY)


def describe_step(step: Any) -> str:
    """One-line label, e.g. ``Tap A``, ``Wait 50 ms`` or ``App: Toggle system monitor``."""
    if isinstance(step, WheelStep):
        return WHEEL_TEXT.get(step.direction, f"Scroll {step.direction}")
    if isinstance(step, AppActionStep):
        return APP_STEP_PREFIX + gui_link.APP_ACTION_LABELS.get(step.action, step.action)
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
    """Edits one key, mouse-button, wheel, delay or app-action step; the delay is bounded to MIN..MAX_DELAY_MS."""

    def __init__(self, step: Any = None, parent: QWidget | None = None, *, engine: Any = None,
                 identity: str | None = None, device_name: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(STEP_TITLE)
        self._engine = engine
        self._identity = identity
        self._device_name = device_name
        self.recorder: RecorderDialog | None = None
        step = step if step is not None else KeyStep(DEFAULT_KEY)
        self.kind_combo = QComboBox(self)
        for kind, label in KIND_LABELS:
            self.kind_combo.addItem(label, kind)
        self._build_fields(step)
        kind = step_kind(step)
        self.kind_combo.setCurrentIndex(max(0, self.kind_combo.findData(kind)))
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        self._build_layout()
        self._set_tab_order()
        self.kind_combo.currentIndexChanged.connect(self._update_fields)
        self.capture_button.clicked.connect(self._capture_key)
        self._update_fields()

    def _build_fields(self, step: Any) -> None:
        """Create the per-kind editors, prefilled from ``step`` where it matches."""
        is_key = isinstance(step, KeyStep)
        self.code_combo = key_combo(self, step.code if is_key else DEFAULT_KEY, "Key or button")
        self._can_capture = (self._engine is not None and self._identity is not None
                             and bool(self._device_name))
        self.capture_button = QPushButton("&Capture\u2026", self)
        if not self._can_capture:
            self.capture_button.setToolTip(NO_ENGINE_TIP)
        self.action_combo = QComboBox(self)
        for action, label in ACTION_LABELS:
            self.action_combo.addItem(label, action)
        if is_key:
            self.action_combo.setCurrentIndex(max(0, self.action_combo.findData(step.action)))
        self.mouse_combo = QComboBox(self)
        self.mouse_combo.setAccessibleName("Mouse button")
        for name in keycodes.MOUSE_BUTTON_NAMES:
            self.mouse_combo.addItem(keycodes.display_name(name), name)
        if step_kind(step) == KIND_MOUSE:
            self.mouse_combo.setCurrentIndex(self.mouse_combo.findData(step.code))
        self.wheel_combo = QComboBox(self)
        self.wheel_combo.setAccessibleName("Wheel direction")
        for direction, label in WHEEL_LABELS:
            self.wheel_combo.addItem(label, direction)
        if isinstance(step, WheelStep):
            self.wheel_combo.setCurrentIndex(max(0, self.wheel_combo.findData(step.direction)))
        self.delay_spin = QSpinBox(self)
        self.delay_spin.setRange(model.MIN_DELAY_MS, model.MAX_DELAY_MS)
        self.delay_spin.setSuffix(DELAY_SUFFIX)
        self.delay_spin.setValue(step.ms if isinstance(step, DelayStep) else DEFAULT_DELAY_MS)
        self.app_combo = QComboBox(self)
        self.app_combo.setAccessibleName("App action")
        for action, label in gui_link.APP_ACTION_LABELS.items():
            self.app_combo.addItem(label, action)
        if isinstance(step, AppActionStep):
            if self.app_combo.findData(step.action) < 0:
                self.app_combo.addItem(step.action, step.action)
            self.app_combo.setCurrentIndex(self.app_combo.findData(step.action))

    def _build_layout(self) -> None:
        form = QFormLayout()
        layouts.configure_form(form)
        theme.set_role(self.buttons.button(QDialogButtonBox.StandardButton.Ok), "primary")
        form.addRow("&Type:", self.kind_combo)
        key_row = QHBoxLayout()
        key_row.addWidget(self.code_combo, 1)
        key_row.addWidget(self.capture_button)
        form.addRow("&Key:", key_row)
        form.addRow("&Button:", self.mouse_combo)
        form.addRow("Di&rection:", self.wheel_combo)
        form.addRow("&Action:", self.action_combo)
        form.addRow("&Delay:", self.delay_spin)
        form.addRow("A&pp action:", self.app_combo)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.buttons)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

    def _set_tab_order(self) -> None:
        """Make Tab follow the visual order: type, key, button, direction, action, delay, app action, OK/Cancel."""
        chain = [self.kind_combo, self.code_combo, self.capture_button, self.mouse_combo,
                 self.wheel_combo, self.action_combo, self.delay_spin,
                 self.app_combo, self.buttons.button(QDialogButtonBox.StandardButton.Ok),
                 self.buttons.button(QDialogButtonBox.StandardButton.Cancel)]
        for first, second in zip(chain, chain[1:]):
            QWidget.setTabOrder(first, second)

    def _update_fields(self) -> None:
        kind = self.kind_combo.currentData()
        self.code_combo.setEnabled(kind == KIND_KEY)
        self.mouse_combo.setEnabled(kind == KIND_MOUSE)
        self.wheel_combo.setEnabled(kind == KIND_WHEEL)
        self.action_combo.setEnabled(kind in (KIND_KEY, KIND_MOUSE))
        self.delay_spin.setEnabled(kind == KIND_DELAY)
        self.app_combo.setEnabled(kind == KIND_APP)
        self.capture_button.setEnabled(kind == KIND_KEY and self._can_capture)

    def _capture_key(self) -> None:
        self.recorder = RecorderDialog(self._engine, self._identity, capture=True, parent=self,
                                       device_name=self._device_name)
        self.recorder.accepted.connect(lambda dialog=self.recorder: self._key_captured(dialog))
        self.recorder.open()

    def _key_captured(self, dialog: RecorderDialog) -> None:
        if dialog.captured is not None:
            self.code_combo.setCurrentText(dialog.captured)

    def step(self) -> Any:
        """The edited step."""
        kind = self.kind_combo.currentData()
        if kind == KIND_MOUSE:
            return KeyStep(self.mouse_combo.currentData(), self.action_combo.currentData())
        if kind == KIND_WHEEL:
            return WheelStep(self.wheel_combo.currentData())
        if kind == KIND_DELAY:
            return DelayStep(self.delay_spin.value())
        if kind == KIND_APP:
            return AppActionStep(self.app_combo.currentData())
        return KeyStep(self.code_combo.currentText().strip(), self.action_combo.currentData())


class MacroEditorDialog(QDialog):
    """Edits a copy of ``macro``; :meth:`macro` returns the result once accepted.

    ``engine`` + ``identity`` enable recording; ``device_name`` (the evdev name) also enables trigger capture;
    ``taken_triggers`` are triggers of the device's other macros;
    ``also_identities`` are further devices the recorder records beside ``identity``.
    """

    def __init__(self, macro: Macro, *, engine: Any = None, identity: str | None = None,
                 taken_triggers: Iterable[str] = (), parent: QWidget | None = None,
                 device_name: str | None = None, also_identities: Iterable[str] = ()) -> None:
        super().__init__(parent)
        self.setWindowTitle(EDITOR_TITLE)
        self._id = macro.id
        self._engine = engine
        self._identity = identity
        self._taken = set(taken_triggers)
        self._device_name = device_name or None
        self._also_identities = tuple(also_identities)
        self._steps = list(macro.steps)
        self.step_dialog: StepDialog | None = None
        self.recorder: RecorderDialog | None = None
        self.review: ReviewDialog | None = None
        self._build_fields(macro)
        self._build_step_buttons()
        self._build_layout()
        self._set_tab_order()
        self._connect_signals()
        self._refresh_steps()

    # -- construction --------------------------------------------------------

    def _build_fields(self, macro: Macro) -> None:
        self.name_edit = QLineEdit(macro.name, self)
        self.name_edit.setMaxLength(model.MAX_NAME_LENGTH)
        self.enabled_check = QCheckBox("E&nabled", self)
        self.enabled_check.setChecked(macro.enabled)
        self._build_repeat(macro)
        self.trigger_combo = key_combo(self, macro.trigger, "Trigger")
        self.capture_button = QPushButton("&Capture\u2026", self)
        self.steps_list = QListWidget(self)
        self.steps_list.setAccessibleName("Steps")
        self.steps_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.validation_label = QLabel(self)
        self.validation_label.setWordWrap(True)
        self.validation_label.setAccessibleName("Validation")
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        theme.set_role(self.buttons.button(QDialogButtonBox.StandardButton.Ok), "primary")

    def _build_repeat(self, macro: Macro) -> None:
        """Build the repeat-mode group and expose its controls as editor attributes."""
        self.repeat_group = RepeatModeGroup(macro.repeat_mode, macro.repeat_count, self)
        self.repeat_once_radio = self.repeat_group.once_radio
        self.repeat_times_radio = self.repeat_group.times_radio
        self.repeat_toggle_radio = self.repeat_group.toggle_radio
        self.repeat_count_spin = self.repeat_group.count_spin

    def _build_step_buttons(self) -> None:
        labels = {"add_key": "Add &key\u2026", "add_delay": "Add &delay\u2026",
                  "edit": "&Edit\u2026", "up": "Move &up", "down": "Move do&wn",
                  "delete": "De&lete", "record": "&Record\u2026"}
        for key, text in labels.items():
            setattr(self, f"{key}_button", QPushButton(text, self))
        can_record = self._engine is not None and self._identity is not None
        can_capture = can_record and bool(self._device_name)
        for button, usable in ((self.record_button, can_record), (self.capture_button, can_capture)):
            button.setEnabled(usable)
            if not usable:
                button.setToolTip(NO_ENGINE_TIP)

    def _build_layout(self) -> None:
        trigger_row = QHBoxLayout()
        trigger_row.addWidget(self.trigger_combo, 1)
        trigger_row.addWidget(self.capture_button)
        form = QFormLayout()
        layouts.configure_form(form)
        form.addRow("&Name:", self.name_edit)
        form.addRow("&Trigger:", trigger_row)
        form.addRow("", self.enabled_check)
        form.addRow("Repeat:", self.repeat_group)
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

    def _set_tab_order(self) -> None:
        """Make Tab follow the visual order: fields, repeat group, steps, step buttons, OK/Cancel."""
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        cancel = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        chain = [self.name_edit, self.trigger_combo, self.capture_button, self.enabled_check,
                 self.repeat_once_radio, self.repeat_times_radio, self.repeat_count_spin,
                 self.repeat_toggle_radio, self.steps_list, self.add_key_button,
                 self.add_delay_button, self.record_button, self.edit_button, self.up_button,
                 self.down_button, self.delete_button, ok, cancel]
        for first, second in zip(chain, chain[1:]):
            QWidget.setTabOrder(first, second)

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
        self.steps_list.itemSelectionChanged.connect(self._update_buttons)
        self.name_edit.textChanged.connect(lambda _text: self._validate())
        self.trigger_combo.currentTextChanged.connect(lambda _text: self._validate())
        self.repeat_group.changed.connect(self._validate)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

    # -- public API ----------------------------------------------------------

    def macro(self) -> Macro:
        """The macro as currently edited."""
        return Macro(id=self._id, name=self.name_edit.text().strip(),
                     enabled=self.enabled_check.isChecked(),
                     trigger=self.trigger_combo.currentText().strip(), steps=list(self._steps),
                     repeat_mode=self.repeat_group.mode(), repeat_count=self.repeat_group.count())

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
        self.step_dialog = StepDialog(step, self, engine=self._engine, identity=self._identity,
                                      device_name=self._device_name)
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

    def _selected_rows(self) -> list[int]:
        """Rows of all selected steps, ascending."""
        return sorted(self.steps_list.row(item) for item in self.steps_list.selectedItems())

    def _delete_current(self) -> None:
        rows = [row for row in self._selected_rows() if 0 <= row < len(self._steps)]
        if not rows:
            return
        if len(rows) > 1:
            answer = QMessageBox.question(self, EDITOR_TITLE, DELETE_MANY_TEXT.format(len(rows)))
            if answer != QMessageBox.StandardButton.Yes:
                return
        for row in reversed(rows):
            del self._steps[row]
        self._refresh_steps(min(rows[0], len(self._steps) - 1))

    def _open_recorder(self, capture: bool) -> None:
        self.recorder = RecorderDialog(self._engine, self._identity, capture=capture, parent=self,
                                       device_name=self._device_name,
                                       also_identities=self._also_identities)
        on_done: Callable[[RecorderDialog], None] = self._captured if capture else self._recorded
        self.recorder.accepted.connect(lambda dialog=self.recorder: on_done(dialog))
        self.recorder.open()

    def _recorded(self, dialog: RecorderDialog) -> None:
        self.review = ReviewDialog(dialog.steps, self)
        self.review.accepted.connect(lambda review=self.review: self._insert_reviewed(review))
        self.review.open()

    def _insert_reviewed(self, review: ReviewDialog) -> None:
        steps = review.steps()
        if steps:
            self._insert(steps)

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
        selected = bool(self.steps_list.selectedItems())
        single = (len(self.steps_list.selectedItems()) == 1
                  and self.steps_list.selectedItems()[0] is self.steps_list.currentItem()
                  and 0 <= row < len(self._steps))
        self.edit_button.setEnabled(bool(single))
        self.delete_button.setEnabled(selected)
        self.up_button.setEnabled(bool(single) and row > 0)
        self.down_button.setEnabled(bool(single) and row < len(self._steps) - 1)
        full = len(self._steps) >= model.MAX_STEPS
        self.add_key_button.setEnabled(not full)
        self.add_delay_button.setEnabled(not full)

    def _validate(self) -> None:
        found = self.problems()
        self.validation_label.setText("\n".join(found) if found else VALID_TEXT)
        theme.set_role(self.validation_label, "error" if found else "muted")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not found)
