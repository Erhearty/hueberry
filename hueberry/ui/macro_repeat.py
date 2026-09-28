# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Repeat-mode controls of the macro editor: play once, N times, or as a toggle loop.

Kept apart from :mod:`hueberry.ui.macro_editor` so the editor module stays small.
"""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup, QHBoxLayout, QLabel, QRadioButton, QSpinBox, QVBoxLayout, QWidget,
)

from hueberry.macros.model import (
    MAX_REPEAT_COUNT, MIN_REPEAT_COUNT, REPEAT_ONCE, REPEAT_TIMES, REPEAT_TOGGLE,
)
from hueberry.ui import theme

MODE_TEXTS = ((REPEAT_ONCE, "Play &once"), (REPEAT_TIMES, "Play N ti&mes"),
              (REPEAT_TOGGLE, "To&ggle loop (press again to stop)"))
COUNT_LABEL_TEXT = "Repe&at count:"
STOP_HINT_TEXT = "Pressing the trigger again stops a toggle or N-times loop."


class RepeatModeGroup(QWidget):
    """Radios for once / N times / toggle loop, the N spin box and a muted stop hint.

    ``changed`` fires whenever the mode or the count changes.
    """

    changed = pyqtSignal()

    def __init__(self, mode: str = REPEAT_ONCE, count: int = MIN_REPEAT_COUNT,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._radios: dict[str, QRadioButton] = {}
        self._buttons = QButtonGroup(self)
        for key, text in MODE_TEXTS:
            radio = QRadioButton(text, self)
            radio.setAccessibleName(text.replace("&", ""))
            self._buttons.addButton(radio)
            self._radios[key] = radio
        self.once_radio = self._radios[REPEAT_ONCE]
        self.times_radio = self._radios[REPEAT_TIMES]
        self.toggle_radio = self._radios[REPEAT_TOGGLE]
        self.count_spin = QSpinBox(self)
        self.count_spin.setRange(MIN_REPEAT_COUNT, MAX_REPEAT_COUNT)
        self.count_spin.setAccessibleName("Repeat count")
        self._kept_count: int | None = None  # the unclamped count of a non-'times' macro
        self._build_layout()
        self.set_value(mode, count)
        self._buttons.buttonToggled.connect(lambda _button, _checked: self._on_changed())
        self.count_spin.valueChanged.connect(lambda _value: self._on_count_edited())

    def _build_layout(self) -> None:
        """Stack the radios; the count spin (with its buddy label) sits beside 'N times'."""
        self.count_label = QLabel(COUNT_LABEL_TEXT, self)
        self.count_label.setBuddy(self.count_spin)
        self.hint_label = QLabel(STOP_HINT_TEXT, self)
        self.hint_label.setWordWrap(True)
        theme.set_role(self.hint_label, "muted")
        times_row = QHBoxLayout()
        times_row.setSpacing(theme.SPACING_S)
        times_row.addWidget(self.times_radio)
        times_row.addWidget(self.count_label)
        times_row.addWidget(self.count_spin)
        times_row.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACING_S)
        layout.addWidget(self.once_radio)
        layout.addLayout(times_row)
        layout.addWidget(self.toggle_radio)
        layout.addWidget(self.hint_label)

    def mode(self) -> str:
        """The checked repeat mode (REPEAT_ONCE when none is checked)."""
        for key, radio in self._radios.items():
            if radio.isChecked():
                return key
        return REPEAT_ONCE

    def count(self) -> int:
        """The spin box count, or the original count of a non-'times' macro left unedited."""
        if self._kept_count is None or self.mode() == REPEAT_TIMES:
            return self.count_spin.value()
        return self._kept_count

    def set_value(self, mode: str, count: int) -> None:
        """Show ``mode`` (unknown modes fall back to once) and ``count`` (clamped).

        Outside 'times' the count is not range-checked, so the original is remembered and
        returned by :meth:`count` until 'times' is chosen or the spin box is edited.
        """
        self._radios.get(mode, self.once_radio).setChecked(True)
        self.count_spin.setValue(count)
        self._kept_count = None if self.mode() == REPEAT_TIMES else count
        self._update_enabled()

    def _update_enabled(self) -> None:
        """The count only matters while 'N times' is checked."""
        is_times = self.mode() == REPEAT_TIMES
        self.count_spin.setEnabled(is_times)
        self.count_label.setEnabled(is_times)

    def _on_count_edited(self) -> None:
        """Spin slot: an edited count replaces the remembered one, then report the change."""
        self._kept_count = None
        self.changed.emit()

    def _on_changed(self) -> None:
        """Radio slot: update the spin state, then report the change."""
        self._update_enabled()
        self.changed.emit()
