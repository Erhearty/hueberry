# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Key groups of one device on the Effects page: the group list and its effect editor.

The pure functions edit a :class:`DeviceProgram` (a key belongs to at most
one group, so adding or assigning keys takes them from the other groups);
:class:`GroupsPanel` is the widget column that drives them and emits
``program_changed(DeviceProgram)`` after every edit.
"""

import logging
import random
from typing import Iterable

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QGridLayout, QLabel, QLineEdit, QListWidget, QPushButton, QVBoxLayout, QWidget,
)

from hueberry.backend.advanced_presets import MAX_LABEL_LENGTH, Cell, DeviceProgram, KeyGroup
from hueberry.backend.key_effect_render import render_group
from hueberry.backend.key_effects import KeyEffect
from hueberry.ui.key_effect_editor import KeyEffectEditor

__all__ = ["GroupsPanel", "add_group", "assign_keys", "next_group_name", "program_colours",
           "remove_group", "rename_group"]

logger = logging.getLogger(__name__)

RGB = tuple[int, int, int]
GROUP_NAME = "Group {number}"
FIRST_GROUP_NUMBER = 1
NO_ROW = -1
ITEM_TEXT = "{name} ({count} keys)"
BUTTON_COLUMNS = 2


def _without(groups: Iterable[KeyGroup], cells: frozenset[Cell]) -> tuple[KeyGroup, ...]:
    return tuple(g.with_changes(leds=tuple(c for c in g.leds if c not in cells)) for g in groups)


def next_group_name(program: DeviceProgram) -> str:
    """The first unused ``Group N`` name of ``program``."""
    taken = {group.name for group in program.groups}
    number = FIRST_GROUP_NUMBER
    while GROUP_NAME.format(number=number) in taken:
        number += 1
    return GROUP_NAME.format(number=number)


def add_group(program: DeviceProgram, cells: Iterable[Cell],
              name: str | None = None, effect: KeyEffect | None = None) -> DeviceProgram:
    """A copy of ``program`` with a new group of ``cells`` (taken from other groups)."""
    cells = frozenset(cells)
    group = KeyGroup(name or next_group_name(program), tuple(sorted(cells)),
                     effect if effect is not None else KeyEffect())
    return DeviceProgram(program.serial, _without(program.groups, cells) + (group,), program.name)


def assign_keys(program: DeviceProgram, index: int, cells: Iterable[Cell]) -> DeviceProgram:
    """A copy where group ``index`` holds exactly ``cells`` (taken from other groups)."""
    cells = frozenset(cells)
    groups = list(_without(program.groups, cells))
    groups[index] = groups[index].with_changes(leds=tuple(sorted(cells)))
    return DeviceProgram(program.serial, tuple(groups), program.name)


def rename_group(program: DeviceProgram, index: int, name: str) -> DeviceProgram:
    """A copy where group ``index`` is called ``name``."""
    groups = list(program.groups)
    groups[index] = groups[index].with_changes(name=name)
    return DeviceProgram(program.serial, tuple(groups), program.name)


def set_group_effect(program: DeviceProgram, index: int, effect: KeyEffect) -> DeviceProgram:
    """A copy where group ``index`` shows ``effect``."""
    groups = list(program.groups)
    groups[index] = groups[index].with_changes(effect=effect)
    return DeviceProgram(program.serial, tuple(groups), program.name)


def remove_group(program: DeviceProgram, index: int) -> DeviceProgram:
    """A copy without group ``index``."""
    groups = program.groups[:index] + program.groups[index + 1:]
    return DeviceProgram(program.serial, groups, program.name)


def program_colours(program: DeviceProgram, t_seconds: float,
                    rng: random.Random) -> dict[Cell, RGB]:
    """Preview colours of every grouped key at ``t_seconds`` (no key presses)."""
    colours: dict[Cell, RGB] = {}
    for group in program.groups:
        try:
            colours.update(render_group(group.effect, group.leds, t_seconds, [], rng))
        except Exception:  # a broken effect must not stop the preview
            logger.warning("Previewing group %s failed", group.name, exc_info=True)
    return colours


class GroupsPanel(QWidget):
    """Group list with Add/Assign/Rename/Remove and the chosen group's effect editor."""

    program_changed = pyqtSignal(object)  # DeviceProgram
    group_chosen = pyqtSignal(object)  # frozenset of the chosen group's keys

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._program: DeviceProgram | None = None
        self._selection: frozenset[Cell] = frozenset()
        self._build()
        self._connect()
        self._update_buttons()

    def _build(self) -> None:
        self.group_list = QListWidget(self)
        self.group_list.setAccessibleName("Key groups")
        self.name_edit = QLineEdit(self)
        self.name_edit.setMaxLength(MAX_LABEL_LENGTH)
        self.name_edit.setAccessibleName("Group name")
        self.name_edit.setPlaceholderText("Group name")
        self.add_button = QPushButton("Add &group from selection", self)
        self.assign_button = QPushButton("Assign selected &keys", self)
        self.rename_button = QPushButton("&Rename", self)
        self.remove_button = QPushButton("Re&move group", self)
        self.editor = KeyEffectEditor(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        name_label = QLabel("Key &groups:", self)
        name_label.setBuddy(self.group_list)
        layout.addWidget(name_label)
        layout.addWidget(self.group_list)
        layout.addWidget(self.name_edit)
        buttons = QGridLayout()
        for index, button in enumerate((self.add_button, self.assign_button,
                                        self.rename_button, self.remove_button)):
            buttons.addWidget(button, index // BUTTON_COLUMNS, index % BUTTON_COLUMNS)
        layout.addLayout(buttons)
        layout.addWidget(self.editor)

    def _connect(self) -> None:
        self.group_list.currentRowChanged.connect(self._on_row)
        self.name_edit.textChanged.connect(lambda _text: self._update_buttons())
        self.name_edit.returnPressed.connect(self._rename)
        self.add_button.clicked.connect(self._add)
        self.assign_button.clicked.connect(self._assign)
        self.rename_button.clicked.connect(self._rename)
        self.remove_button.clicked.connect(self._remove)
        self.editor.effect_changed.connect(self._on_effect)

    # -- public API --------------------------------------------------------------

    def set_program(self, program: DeviceProgram | None) -> None:
        """Show the groups of ``program`` (None: no device)."""
        self._program = program
        self._show(0 if program is not None and program.groups else NO_ROW)

    def program(self) -> DeviceProgram | None:
        """The program as edited."""
        return self._program

    def set_selection(self, cells: Iterable[Cell]) -> None:
        """The keys currently selected on the device (used by Add and Assign)."""
        self._selection = frozenset(cells)
        self._update_buttons()

    def current_index(self) -> int:
        """Row of the chosen group, or -1."""
        return self.group_list.currentRow()

    # -- internals ---------------------------------------------------------------

    def _show(self, row: int) -> None:
        self.group_list.blockSignals(True)
        self.group_list.clear()
        for group in self._program.groups if self._program is not None else ():
            self.group_list.addItem(ITEM_TEXT.format(name=group.name, count=len(group.leds)))
        self.group_list.setCurrentRow(row)
        self.group_list.blockSignals(False)
        self._on_row(self.group_list.currentRow(), announce=False)

    def _group(self) -> KeyGroup | None:
        row = self.group_list.currentRow()
        if self._program is None or not 0 <= row < len(self._program.groups):
            return None
        return self._program.groups[row]

    def _on_row(self, _row: int, announce: bool = True) -> None:
        group = self._group()
        self.editor.setEnabled(group is not None)
        if group is not None:
            self.editor.set_effect(group.effect)
            self.name_edit.setText(group.name)
            if announce:
                self.group_chosen.emit(frozenset(group.leds))
        self._update_buttons()

    def _update_buttons(self) -> None:
        has_program = self._program is not None
        chosen = self._group() is not None
        self.add_button.setEnabled(has_program and bool(self._selection))
        self.assign_button.setEnabled(chosen)
        self.rename_button.setEnabled(chosen and bool(self.name_edit.text().strip()))
        self.remove_button.setEnabled(chosen)
        self.name_edit.setEnabled(has_program)

    def _commit(self, program: DeviceProgram, row: int) -> None:
        self._program = program
        self._show(row)
        self.program_changed.emit(program)

    def _add(self) -> None:
        if self._program is None or not self._selection:
            return
        self._commit(add_group(self._program, self._selection), len(self._program.groups))

    def _assign(self) -> None:
        row = self.current_index()
        if self._group() is not None:
            self._commit(assign_keys(self._program, row, self._selection), row)

    def _rename(self) -> None:
        name, row = self.name_edit.text().strip(), self.current_index()
        if self._group() is not None and name:
            self._commit(rename_group(self._program, row, name), row)

    def _remove(self) -> None:
        row = self.current_index()
        if self._group() is not None:
            remaining = len(self._program.groups) - 1
            self._commit(remove_group(self._program, row), min(row, remaining - 1))

    def _on_effect(self, effect: KeyEffect) -> None:
        row = self.current_index()
        if self._group() is None:
            return
        self._program = set_group_effect(self._program, row, effect)
        self.program_changed.emit(self._program)
