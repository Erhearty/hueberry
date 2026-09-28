# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Row widgets of the Macros page lists: a device row and a macro row.

Rows are shown with ``QListWidget.setItemWidget`` over items that keep their own
text, check state and data, so the lists stay keyboard-driven and accessible.
"""

from typing import Any

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QListWidget, QWidget

from hueberry.macros import keycodes
from hueberry.macros.model import REPEAT_TIMES, REPEAT_TOGGLE, Macro
from hueberry.ui import device_icons, theme

ROW_OBJECT_NAME = "listRow"
STATE_CHIP_NAME = "stateChip"
TRIGGER_CHIP_NAME = "triggerChip"
REPEAT_BADGE_NAME = "repeatBadge"
SELECTED_PROPERTY = "selected"
STATE_PROPERTY = "state"
ICON_PX = 24
FALLBACK_DEVICE_TYPE = "keyboard"  # rows without a known kind; most macro devices have keys
KNOWN_KINDS = (device_icons.KIND_KEYBOARD, device_icons.KIND_MOUSE)  # kinds the engine reports
IDLE_STATE = "idle"
OFFLINE_STATE = "offline"
ONCE_BADGE = "Once"
TIMES_BADGE = "\u00d7{count}"
TOGGLE_BADGE = "\u221e Toggle"
SWITCH_NAME = "Enabled: {name}"


def set_dynamic_property(widget: QWidget, name: str, value: Any) -> None:
    """Set a stylesheet-visible property on ``widget`` and re-polish it."""
    widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def repeat_badge_text(macro: Macro) -> str:
    """Badge for the macro's repeat mode: 'Once', '×N' or '∞ Toggle'."""
    if macro.repeat_mode == REPEAT_TOGGLE:
        return TOGGLE_BADGE
    if macro.repeat_mode == REPEAT_TIMES:
        return TIMES_BADGE.format(count=macro.repeat_count)
    return ONCE_BADGE


def steps_text(count: int) -> str:
    """'1 step' or 'N steps'."""
    return f"{count} step" if count == 1 else f"{count} steps"


def _chip(text: str, object_name: str, parent: QWidget) -> QLabel:
    """A small bordered label styled by its object name."""
    chip = QLabel(text, parent)
    chip.setObjectName(object_name)
    return chip


class ListRow(QWidget):
    """Base row: styled background, a horizontal layout and a 'selected' look."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(ROW_OBJECT_NAME)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.row_layout = QHBoxLayout(self)
        self.row_layout.setContentsMargins(theme.SPACING_S, theme.SPACING_S,
                                           theme.SPACING_S, theme.SPACING_S)
        self.row_layout.setSpacing(theme.SPACING_S)

    def set_selected(self, selected: bool) -> None:
        """Show the row as the list's current row (accent edge) or not."""
        if bool(self.property(SELECTED_PROPERTY)) != selected:
            set_dynamic_property(self, SELECTED_PROPERTY, selected)


def icon_kind(name: str, kind: str | None) -> str:
    """Icon type of a device row: the engine's kind if known, else a guess from the name."""
    if kind is not None and kind in KNOWN_KINDS:
        return kind
    guessed = device_icons.kind_for_type(name)
    return guessed if guessed != device_icons.KIND_GENERIC else FALLBACK_DEVICE_TYPE


class DeviceRow(ListRow):
    """Icon, device name and a state chip whose ``state`` property drives its colour."""

    def __init__(self, name: str, state: str, label: str, parent: QWidget | None = None,
                 kind: str | None = None) -> None:
        super().__init__(parent)
        self.icon_kind = icon_kind(name, kind)
        self.icon_label = QLabel(self)
        self.icon_label.setPixmap(device_icons.pixmap_for_type(self.icon_kind, ICON_PX))
        self.name_label = QLabel(name, self)
        self.state_chip = _chip(label, STATE_CHIP_NAME, self)
        set_dynamic_property(self.state_chip, STATE_PROPERTY, state)
        self.row_layout.addWidget(self.icon_label)
        self.row_layout.addWidget(self.name_label, 1)
        self.row_layout.addWidget(self.state_chip)


class MacroRow(ListRow):
    """Enabled switch, bold name, trigger chip, repeat badge and the step count."""

    def __init__(self, macro: Macro, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.enabled_check = QCheckBox(self)
        self.enabled_check.setChecked(macro.enabled)
        self.enabled_check.setAccessibleName(SWITCH_NAME.format(name=macro.name))
        # The list owns keyboard focus: Space toggles the item, which syncs this switch.
        self.enabled_check.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.name_label = QLabel(macro.name, self)
        font = self.name_label.font()
        font.setBold(True)
        self.name_label.setFont(font)
        self.trigger_chip = _chip(keycodes.display_name(macro.trigger), TRIGGER_CHIP_NAME, self)
        self.repeat_badge = _chip(repeat_badge_text(macro), REPEAT_BADGE_NAME, self)
        self.steps_label = QLabel(steps_text(len(macro.steps)), self)
        theme.set_role(self.steps_label, "muted")
        for widget in (self.enabled_check, self.name_label, self.trigger_chip):
            self.row_layout.addWidget(widget)
        self.row_layout.addStretch(1)
        self.row_layout.addWidget(self.repeat_badge)
        self.row_layout.addWidget(self.steps_label)

    def set_checked(self, checked: bool) -> None:
        """Show ``checked`` on the switch without emitting ``toggled``."""
        self.enabled_check.blockSignals(True)
        self.enabled_check.setChecked(checked)
        self.enabled_check.blockSignals(False)


class SpaceToggleFilter(QObject):
    """Event filter making Space (or Select) toggle the check state of a list's current item."""

    TOGGLE_KEYS = (Qt.Key.Key_Space, Qt.Key.Key_Select)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt API)
        """Toggle on a toggle key press over a checkable current item; pass everything else."""
        if not (isinstance(watched, QListWidget) and isinstance(event, QKeyEvent)
                and event.type() == QEvent.Type.KeyPress and event.key() in self.TOGGLE_KEYS):
            return False
        item = watched.currentItem()
        if item is None or not item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            return False
        checked = item.checkState() == Qt.CheckState.Checked
        item.setCheckState(Qt.CheckState.Unchecked if checked else Qt.CheckState.Checked)
        return True


def mark_current(view: QListWidget) -> None:
    """Give the row widget of ``view``'s current item the selected look, and clear the others."""
    current = view.currentRow()
    for row in range(view.count()):
        widget = view.itemWidget(view.item(row))
        if isinstance(widget, ListRow):
            widget.set_selected(row == current)
