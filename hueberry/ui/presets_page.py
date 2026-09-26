# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Presets page: the preset library, the preset editor and an 'Apply to' section.

User presets are edited in memory and written to presets.json by *Save*
(through ``worker.run_async``, looked up on the module so tests can run it
inline); a saved preset that is running is swapped in on the animator. The
'Apply to' section starts a preset on each checked device on its own, or on
all of them as one synced group, and stops it again.
"""

import logging
from typing import Any, Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup, QGroupBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QRadioButton, QVBoxLayout, QWidget,
)

from hueberry.backend import animator, preset_store
from hueberry.backend.effects import EFFECT_WAVE, MAX_LABEL_LENGTH, Preset, PresetError
from hueberry.ui import theme, worker
from hueberry.ui.preset_editor import PresetEditor

__all__ = ["PresetsPage"]

logger = logging.getLogger(__name__)

TITLE_TEXT = "<b>Lighting presets</b>"
BACK_TEXT = "\u2190 Back"
BUILTIN_SUFFIX = " (built-in)"
UNSAVED_SUFFIX = " *"
NEW_PRESET_LABEL = "New preset"
COPY_SUFFIX = " (copy)"
NEW_PALETTE = ((0x26, 0xB5, 0xA0), (0xFF, 0xFF, 0xFF))  # the theme accent, then white
KEY_ROLE = Qt.ItemDataRole.UserRole
SERIAL_ROLE = Qt.ItemDataRole.UserRole
SAVED_TEXT = "Presets saved"
SAVE_FAILED_TEXT = "Saving presets failed: {error}"
UPDATE_FAILED_TEXT = "Presets saved, but running animations were not updated: {error}"
LOAD_FAILED_TEXT = "Presets could not be loaded: {error}"
NO_DEVICES_TEXT = "Tick at least one device first"
APPLIED_TEXT = "{label} applied to {count} device(s)"
APPLY_FAILED_TEXT = "Applying {label} failed: {error}"
NOT_SUPPORTED_TEXT = "{label} is not supported on the selected devices"
STOPPED_TEXT = "Stopped {count} device(s)"
STOP_FAILED_TEXT = "Stopping failed: {error}"
INVALID_TEXT = "Cannot apply: {error}"


class PresetsPage(QWidget):
    """Preset list, editor, New/Duplicate/Delete/Save and Apply/Stop to devices."""

    back_requested = pyqtSignal()
    status = pyqtSignal(str)
    presets_saved = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._user, self._load_error = preset_store.load()
        self._dirty_keys: set[str] = set()  # user presets edited since the last save
        self._devices: dict[str, Any] = {}  # serial -> device object (supported ones)
        self._build_widgets()
        self._build_layout()
        self._connect_signals()
        self._set_tab_order()
        self._show_presets()

    # -- construction --------------------------------------------------------

    def _build_widgets(self) -> None:
        self.back_button = QPushButton(BACK_TEXT, self)
        self.title_label = QLabel(TITLE_TEXT, self)
        self.error_label = QLabel(self)
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet(f"color: {theme.ERROR};")
        self.preset_list = QListWidget(self)
        self.preset_list.setAccessibleName("Presets")
        self.new_button = QPushButton("Ne&w", self)
        self.duplicate_button = QPushButton("D&uplicate", self)
        self.delete_button = QPushButton("&Delete", self)
        self.save_button = QPushButton("&Save", self)
        self.editor = PresetEditor(self)
        self.device_list = QListWidget(self)
        self.device_list.setAccessibleName("Devices to apply the preset to")
        self.single_radio = QRadioButton("&Each device on its own", self)
        self.group_radio = QRadioButton("Synced &group", self)
        self.single_radio.setChecked(True)
        self.mode_group = QButtonGroup(self)
        for radio in (self.single_radio, self.group_radio):
            self.mode_group.addButton(radio)
        self.apply_button = QPushButton("&Apply", self)
        self.stop_button = QPushButton("S&top", self)

    def _build_layout(self) -> None:
        header = QHBoxLayout()
        header.addWidget(self.back_button)
        header.addWidget(self.title_label)
        header.addStretch(1)
        buttons = QVBoxLayout()
        for button in (self.new_button, self.duplicate_button, self.delete_button,
                       self.save_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        library = QVBoxLayout()
        list_label = QLabel("Presets:", self)
        list_label.setBuddy(self.preset_list)
        library.addWidget(list_label)
        library.addWidget(self.preset_list, 1)
        body = QHBoxLayout()
        body.addLayout(library, 1)
        body.addLayout(buttons)
        body.addWidget(self.editor, 2)
        outer = QVBoxLayout(self)
        outer.addLayout(header)
        outer.addWidget(self.error_label)
        outer.addLayout(body, 1)
        outer.addWidget(self._apply_box())

    def _apply_box(self) -> QGroupBox:
        box = QGroupBox("Apply to devices", self)
        devices_label = QLabel("Apply t&o:", box)
        devices_label.setBuddy(self.device_list)
        controls = QVBoxLayout()
        for widget in (self.single_radio, self.group_radio, self.apply_button, self.stop_button):
            controls.addWidget(widget)
        controls.addStretch(1)
        row = QHBoxLayout()
        row.addWidget(self.device_list, 1)
        row.addLayout(controls)
        layout = QVBoxLayout(box)
        layout.addWidget(devices_label)
        layout.addLayout(row)
        return box

    def _connect_signals(self) -> None:
        self.back_button.clicked.connect(self.back_requested)
        self.preset_list.currentRowChanged.connect(lambda _row: self._show_selected())
        self.new_button.clicked.connect(self._new_preset)
        self.duplicate_button.clicked.connect(self._duplicate)
        self.delete_button.clicked.connect(self._delete_selected)
        self.save_button.clicked.connect(self.save)
        self.editor.preset_changed.connect(self._on_edited)
        self.apply_button.clicked.connect(self._apply_clicked)
        self.stop_button.clicked.connect(self._stop_clicked)

    def _set_tab_order(self) -> None:
        chain = [self.back_button, self.preset_list, self.new_button, self.duplicate_button,
                 self.delete_button, self.save_button, self.editor.first_widget()]
        tail = [self.editor.last_widget(), self.device_list, self.single_radio,
                self.group_radio, self.apply_button, self.stop_button]
        for links in (chain, tail):
            for first, second in zip(links, links[1:]):
                QWidget.setTabOrder(first, second)

    # -- public API ----------------------------------------------------------

    def presets(self) -> list[Preset]:
        """Built-in presets first, then the user's (with unsaved edits)."""
        return preset_store.all_presets(self._user)

    def selected_key(self) -> str | None:
        """Key of the selected preset, or None."""
        item = self.preset_list.currentItem()
        return item.data(KEY_ROLE) if item is not None else None

    def select_key(self, key: str) -> None:
        """Select the preset with ``key`` (no-op when unknown)."""
        for row in range(self.preset_list.count()):
            if self.preset_list.item(row).data(KEY_ROLE) == key:
                self.preset_list.setCurrentRow(row)
                return

    def refresh(self) -> None:
        """Re-read presets.json unless there are unsaved edits."""
        if not self._dirty_keys:
            self._user, self._load_error = preset_store.load()
            self._show_presets()

    def set_devices(self, entries: list[tuple[Any, Any]]) -> None:
        """Show the ``(device, DeviceInfo)`` entries that can show presets, keeping ticks."""
        checked = set(self.checked_serials())
        self._devices = {}
        self.device_list.clear()
        for dev, info in entries:
            if not animator.supports(dev):
                continue
            self._devices[info.serial] = dev
            item = QListWidgetItem(info.name or info.serial, self.device_list)
            item.setData(SERIAL_ROLE, info.serial)
            item.setToolTip(info.serial)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            ticked = info.serial in checked
            item.setCheckState(Qt.CheckState.Checked if ticked else Qt.CheckState.Unchecked)
        self._update_buttons()

    def checked_serials(self) -> list[str]:
        """Serials of the ticked devices, in list order."""
        items = (self.device_list.item(row) for row in range(self.device_list.count()))
        return [item.data(SERIAL_ROLE) for item in items
                if item.checkState() == Qt.CheckState.Checked]

    def save(self) -> None:
        """Write the user presets to presets.json in the background."""
        snapshot = list(self._user)
        saved = [p for p in snapshot if p.key in self._dirty_keys]
        self._run(lambda: preset_store.save(snapshot), lambda _r: self._on_saved(saved),
                  lambda message: self._report(SAVE_FAILED_TEXT.format(error=message)))

    # -- list and editing ----------------------------------------------------

    def _show_presets(self, select: str | None = None) -> None:
        select = select or self.selected_key()
        self.preset_list.blockSignals(True)
        self.preset_list.clear()
        for preset in self.presets():
            suffix = BUILTIN_SUFFIX if preset.builtin else ""
            if preset.key in self._dirty_keys:
                suffix += UNSAVED_SUFFIX
            item = QListWidgetItem(f"{preset.label}{suffix}", self.preset_list)
            item.setData(KEY_ROLE, preset.key)
        self.preset_list.blockSignals(False)
        if select:
            self.select_key(select)
        if self.preset_list.currentRow() < 0 and self.preset_list.count():
            self.preset_list.setCurrentRow(0)
        self._show_selected()
        self.error_label.setVisible(self._load_error is not None)
        self.error_label.setText(LOAD_FAILED_TEXT.format(error=self._load_error or ""))

    def _selected(self) -> Preset | None:
        key = self.selected_key()
        return preset_store.find_preset(key, self.presets()) if key else None

    def _show_selected(self) -> None:
        self.editor.set_preset(self._selected())
        self._update_buttons()

    def _update_buttons(self) -> None:
        selected = self._selected()
        self.duplicate_button.setEnabled(selected is not None)
        self.delete_button.setEnabled(selected is not None and not selected.builtin)
        self.save_button.setEnabled(bool(self._dirty_keys))
        has_devices = self.device_list.count() > 0
        self.apply_button.setEnabled(has_devices and selected is not None)
        self.stop_button.setEnabled(has_devices)

    def _on_edited(self, preset: Preset) -> None:
        index = next((i for i, p in enumerate(self._user) if p.key == preset.key), None)
        if index is None:
            return  # built-ins are read-only
        self._user[index] = preset
        self._dirty_keys.add(preset.key)
        item = self.preset_list.currentItem()
        if item is not None:
            item.setText(f"{preset.label}{UNSAVED_SUFFIX}")
        self._update_buttons()

    def _add_user_preset(self, preset: Preset) -> None:
        self._user.append(preset)
        self._dirty_keys.add(preset.key)
        logger.info("Preset %s added (unsaved)", preset.key)
        self._show_presets(select=preset.key)
        self.editor.first_widget().setFocus()

    def _new_preset(self) -> None:
        key = preset_store.unique_key(NEW_PRESET_LABEL, (p.key for p in self._user))
        self._add_user_preset(Preset(key=key, label=NEW_PRESET_LABEL, effect=EFFECT_WAVE,
                                     palette=NEW_PALETTE))

    def _duplicate(self) -> None:
        source = self.editor.preset() or self._selected()
        if source is None:
            return
        label = f"{source.label}{COPY_SUFFIX}"[:MAX_LABEL_LENGTH]
        key = preset_store.unique_key(label, (p.key for p in self._user))
        self._add_user_preset(source.with_changes(key=key, label=label, builtin=False))

    def _delete_selected(self) -> None:
        key = self.selected_key()
        if key is not None:
            self._delete(key)

    def _delete(self, key: str) -> None:
        """Remove the user preset ``key`` (saved by the next Save)."""
        before = len(self._user)
        self._user = [p for p in self._user if p.key != key]
        if len(self._user) == before:
            return  # built-in or unknown
        self._dirty_keys.add(key)  # the deletion itself needs saving
        logger.info("Preset %s deleted (unsaved)", key)
        self._show_presets()

    @worker.ignore_deleted
    def _on_saved(self, saved: list[Preset]) -> None:
        self._dirty_keys.clear()
        self._load_error = None
        self._show_presets()
        if self._update_running(saved):
            self.status.emit(SAVED_TEXT)
        self.presets_saved.emit()

    def _update_running(self, saved: list[Preset]) -> bool:
        """Swap the saved presets into running animations; False (reported) on failure."""
        updated = 0
        try:
            for preset in saved:
                updated += animator.shared_animator().update_preset(preset)
        except Exception as exc:  # a failing animator must not break the save
            logger.exception("Updating running presets failed")
            self._report(UPDATE_FAILED_TEXT.format(error=exc))
            return False
        logger.info("Presets saved; %d running animations updated", updated)
        return True

    # -- apply to devices ----------------------------------------------------

    def _apply_clicked(self) -> None:
        preset = self.editor.preset()
        devs = [self._devices[serial] for serial in self.checked_serials()]
        if preset is None or not devs:
            self.status.emit(NO_DEVICES_TEXT)
            return
        try:
            preset.validate()
        except PresetError as exc:
            self._report(INVALID_TEXT.format(error=exc))
            return
        if self.group_radio.isChecked():
            self._apply_group(devs, preset)
        else:
            self._apply_single(devs, preset)

    def _apply_single(self, devs: list[Any], preset: Preset) -> None:
        """Start ``preset`` on each device in its own run."""
        def job() -> int:
            return sum(1 for dev in devs if animator.shared_animator().start(dev, preset))
        self._run(job, lambda count: self._on_applied(preset, count),
                  lambda message: self._report(APPLY_FAILED_TEXT.format(
                      label=preset.label, error=message)))

    def _apply_group(self, devs: list[Any], preset: Preset) -> None:
        """Start ``preset`` on all devices as one synced group (in list order)."""
        def job() -> int:
            return len(animator.shared_animator().start_group(devs, preset))
        self._run(job, lambda count: self._on_applied(preset, count),
                  lambda message: self._report(APPLY_FAILED_TEXT.format(
                      label=preset.label, error=message)))

    @worker.ignore_deleted
    def _on_applied(self, preset: Preset, count: int) -> None:
        if count:
            self.status.emit(APPLIED_TEXT.format(label=preset.label, count=count))
        else:
            self._report(NOT_SUPPORTED_TEXT.format(label=preset.label))

    def _stop_clicked(self) -> None:
        serials = self.checked_serials()
        if not serials:
            self.status.emit(NO_DEVICES_TEXT)
            return
        self._stop(serials)

    def _stop(self, serials: list[str]) -> None:
        """Stop the animation on each of ``serials`` (restoring the device effect)."""
        def job() -> int:
            return sum(1 for serial in serials if animator.shared_animator().stop(serial))
        self._run(job, lambda count: self.status.emit(STOPPED_TEXT.format(count=count)),
                  lambda message: self._report(STOP_FAILED_TEXT.format(error=message)))

    # -- helpers -------------------------------------------------------------

    def _run(self, fn: Callable[[], Any], on_done: Callable[[Any], None],
             on_error: Callable[[str], None]) -> None:
        """Run ``fn`` through ``worker.run_async``; a failure to start is reported."""
        try:
            worker.run_async(fn, on_done, on_error)
        except Exception as exc:  # never let an exception escape a slot
            logger.exception("Could not start a presets job")
            on_error(str(exc))

    @worker.ignore_deleted
    def _report(self, message: str) -> None:
        logger.warning("Presets: %s", message)
        self.status.emit(message)
