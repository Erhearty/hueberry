# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Dialog reviewing recorded steps: only the checked ones are added to a macro.

Every step is listed with :func:`hueberry.ui.macro_editor.describe_step`. The
shortcuts All / None / Mouse only / Keyboard only set the checks; Mouse only and
Keyboard only uncheck delay and app-action steps.
"""

from typing import Any, Callable, Iterable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from hueberry.macros import keycodes
from hueberry.macros.model import KeyStep, WheelStep
from hueberry.ui import theme

REVIEW_TITLE = "Review recorded steps"
ALL_TEXT = "&All"
NONE_TEXT = "&None"
MOUSE_TEXT = "&Mouse only"
KEYBOARD_TEXT = "&Keyboard only"


def is_mouse_step(step: Any) -> bool:
    """A wheel step or a key step on a mouse button."""
    return isinstance(step, WheelStep) or (
        isinstance(step, KeyStep) and step.code in keycodes.MOUSE_BUTTON_NAMES)


def is_keyboard_step(step: Any) -> bool:
    """A key step on a keyboard key (not on a mouse button)."""
    return isinstance(step, KeyStep) and step.code not in keycodes.MOUSE_BUTTON_NAMES


class ReviewDialog(QDialog):
    """Checkable list of recorded ``steps`` (all checked at first); :meth:`steps` returns the checked ones."""

    def __init__(self, steps: Iterable[Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Imported here: macro_editor imports this module at load time.
        from hueberry.ui.macro_editor import describe_step

        self.setWindowTitle(REVIEW_TITLE)
        self._steps = list(steps)
        self.list_widget = QListWidget(self)
        self.list_widget.setAccessibleName("Recorded steps")
        for step in self._steps:
            item = QListWidgetItem(describe_step(step), self.list_widget)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
        self.all_button = QPushButton(ALL_TEXT, self)
        self.none_button = QPushButton(NONE_TEXT, self)
        self.mouse_button = QPushButton(MOUSE_TEXT, self)
        self.keyboard_button = QPushButton(KEYBOARD_TEXT, self)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        theme.set_role(self.buttons.button(QDialogButtonBox.StandardButton.Ok), "primary")
        shortcuts = QHBoxLayout()
        for button in (self.all_button, self.none_button, self.mouse_button, self.keyboard_button):
            shortcuts.addWidget(button)
        shortcuts.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addLayout(shortcuts)
        layout.addWidget(self.list_widget, 1)
        layout.addWidget(self.buttons)
        self.all_button.clicked.connect(lambda: self._check_where(lambda step: True))
        self.none_button.clicked.connect(lambda: self._check_where(lambda step: False))
        self.mouse_button.clicked.connect(lambda: self._check_where(is_mouse_step))
        self.keyboard_button.clicked.connect(lambda: self._check_where(is_keyboard_step))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

    def _check_where(self, predicate: Callable[[Any], bool]) -> None:
        """Check the rows whose step satisfies ``predicate``; uncheck the others."""
        for row, step in enumerate(self._steps):
            state = Qt.CheckState.Checked if predicate(step) else Qt.CheckState.Unchecked
            self.list_widget.item(row).setCheckState(state)

    def steps(self) -> list:
        """The checked steps, in recording order."""
        return [step for row, step in enumerate(self._steps)
                if self.list_widget.item(row).checkState() == Qt.CheckState.Checked]
