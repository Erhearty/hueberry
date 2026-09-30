# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Effects page: per-key groups and effects on each keyboard, saved as advanced presets.

Pick a device, select keys on its :class:`KeySelector`, make groups of them
and give each group an effect (:mod:`hueberry.ui.effects_groups`). The
toolbar manages named presets in advanced_presets.json and shows one on the
devices through :func:`advanced_runtime.shared_runtime`. Blocking calls go
through ``worker.run_async``; *Activate* remembers the preset for the next
start, *Stop* forgets it. Edits to the active preset are shown live.
"""

import logging
import random
import time
from typing import Any, Callable

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QListWidgetItem, QWidget

from hueberry.backend import advanced_preset_store, advanced_runtime
from hueberry.backend.advanced_presets import MAX_LABEL_LENGTH, AdvancedPreset, DeviceProgram
from hueberry.backend.effects import PresetError
from hueberry.settings import LAST_ADVANCED_PRESET, Settings
from hueberry.ui import effects_layout, worker
from hueberry.ui.effects_groups import program_colours
from hueberry.ui.effects_layout import MatrixDevice
from hueberry.ui.key_selector import KeySelector

__all__ = ["EffectsPage"]

logger = logging.getLogger(__name__)

NEW_LABEL = "New effect"
COPY_SUFFIX = " (copy)"
UNSAVED_SUFFIX = " *"
PREVIEW_FPS = 30
MS_PER_SECOND = 1000
SERIAL_ROLE = Qt.ItemDataRole.UserRole
LOAD_FAILED_TEXT = "Per-key effects could not be loaded: {error}"
SAVED_TEXT = "Saved {label}"
SAVE_FAILED_TEXT = "Saving per-key effects failed: {error}"
INVALID_TEXT = "Cannot use this effect: {error}"
ACTIVATED_TEXT = "{label} active on {count} device(s)"
NOT_CONNECTED_TEXT = "None of the devices of {label} is connected"
ACTIVATE_FAILED_TEXT = "Activating {label} failed: {error}"
STOPPED_TEXT = "Per-key effects stopped"
STOP_FAILED_TEXT = "Stopping failed: {error}"
DELETED_TEXT = "Deleted {label}"
SETTING_FAILED_TEXT = "Could not remember the effect: {error}"


def _new_preset(taken: list[str]) -> AdvancedPreset:
    return AdvancedPreset(advanced_preset_store.unique_key(NEW_LABEL, taken), NEW_LABEL)


class EffectsPage(QWidget):
    """Device list, key selector, key groups and the preset toolbar."""

    back_requested = pyqtSignal()
    status = pyqtSignal(str)

    def __init__(self, settings: Settings | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._presets, self._load_error = advanced_preset_store.load()
        self._current = self._presets[0] if self._presets else _new_preset([])
        self._dirty = False
        self._devices: dict[str, MatrixDevice] = {}
        self._selectors: dict[str, KeySelector] = {}
        self._shapes: dict[str, tuple[int, int]] = {}  # (rows, cols) each selector was built for
        self._rng = random.Random()
        self._started = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(MS_PER_SECOND // PREVIEW_FPS)
        self._timer.timeout.connect(self.render_preview)
        effects_layout.build(self)
        self._connect()
        self._show_presets()

    # -- construction ------------------------------------------------------------

    def _connect(self) -> None:
        self.back_button.clicked.connect(self.back_requested)
        self.preset_combo.activated.connect(self._on_preset_chosen)
        self.label_edit.textEdited.connect(self._on_label_edited)
        self.new_button.clicked.connect(self.new_preset)
        self.save_button.clicked.connect(self.save)
        self.save_as_button.clicked.connect(self.save_as)
        self.delete_button.clicked.connect(self.delete)
        self.activate_button.clicked.connect(self.activate)
        self.stop_button.clicked.connect(self.stop)
        self.device_list.currentRowChanged.connect(lambda _row: self._show_device())
        self.groups.program_changed.connect(self._on_program_changed)
        self.groups.group_chosen.connect(self._select_keys)

    # -- public API --------------------------------------------------------------

    def current_preset(self) -> AdvancedPreset:
        """The preset being edited (with unsaved edits)."""
        return self._current

    def current_serial(self) -> str | None:
        """Serial of the selected device, or None."""
        item = self.device_list.currentItem()
        return item.data(SERIAL_ROLE) if item is not None else None

    def selector(self, serial: str | None = None) -> KeySelector | None:
        """The key selector of ``serial`` (default: the selected device)."""
        return self._selectors.get(serial or self.current_serial() or "")

    def set_devices(self, entries: list[tuple[Any, Any]]) -> None:
        """List the per-key devices among the ``(device, DeviceInfo)`` entries."""
        selected = self.current_serial()
        self._devices = effects_layout.matrix_devices(entries)
        self._sync_selectors()
        self.device_list.blockSignals(True)
        self.device_list.clear()
        for serial, device in self._devices.items():
            item = QListWidgetItem(device.name, self.device_list)
            item.setData(SERIAL_ROLE, serial)
            item.setToolTip(serial)
        serials = list(self._devices)
        self.device_list.setCurrentRow(serials.index(selected) if selected in serials else 0)
        self.device_list.blockSignals(False)
        self._show_device()

    def device_names(self) -> dict[str, str]:
        """OpenRazer name of each listed device, by serial."""
        return {serial: device.name for serial, device in self._devices.items()}

    def select_preset(self, key: str) -> None:
        """Edit the saved preset ``key`` (unsaved edits are dropped)."""
        preset = advanced_preset_store.find_preset(key, self._presets)
        if preset is not None:
            self._current, self._dirty = preset, False
            self._show_presets()

    def new_preset(self) -> None:
        """Start editing a new, empty preset."""
        self._current = _new_preset([p.key for p in self._presets])
        self._dirty = True
        self._show_presets()

    def save(self) -> None:
        """Save the edited preset to advanced_presets.json (in the background)."""
        self._save(self._current.with_changes(label=self._label()))

    def save_as(self) -> None:
        """Save the edited preset under a new key (a copy)."""
        label = self._label()
        if any(p.label == label for p in self._presets):
            label = f"{label}{COPY_SUFFIX}"[:MAX_LABEL_LENGTH]
        taken = [p.key for p in self._presets] + [self._current.key]
        key = advanced_preset_store.unique_key(label, taken)
        self._save(self._current.with_changes(key=key, label=label))

    def delete(self) -> None:
        """Delete the edited preset (stopping it when it is active)."""
        preset = self._current
        remaining = [p for p in self._presets if p.key != preset.key]
        if len(remaining) == len(self._presets):
            self._after_delete(remaining, preset)  # never saved: just drop it
            return
        self._run(lambda: advanced_preset_store.save(remaining),
                  lambda _result: self._after_delete(remaining, preset),
                  lambda message: self._report(SAVE_FAILED_TEXT.format(error=message)))

    def activate(self) -> None:
        """Show the edited preset on its connected devices and remember it."""
        preset = self._current.with_changes(label=self._label())
        try:
            preset.validate()
        except PresetError as exc:
            self._report(INVALID_TEXT.format(error=exc))
            return
        devs = [self._devices[p.serial].dev for p in preset.programs if p.serial in self._devices]
        if not devs:
            self._report(NOT_CONNECTED_TEXT.format(label=preset.label))
            return
        self._run(lambda: advanced_runtime.shared_runtime().activate(preset, devs),
                  lambda serials: self._on_activated(preset, serials),
                  lambda message: self._report(ACTIVATE_FAILED_TEXT.format(
                      label=preset.label, error=message)))

    def stop(self) -> None:
        """Stop the active per-key preset and forget it."""
        self._run(lambda: advanced_runtime.shared_runtime().stop(),
                  lambda _result: self._on_stopped(),
                  lambda message: self._report(STOP_FAILED_TEXT.format(error=message)))

    def render_preview(self) -> None:
        """Paint the selected device's groups on its key selector."""
        selector, serial = self.selector(), self.current_serial()
        if selector is None or serial is None:
            return
        colours = program_colours(self._program(serial), time.monotonic() - self._started,
                                  self._rng)
        selector.set_colours(colours)

    # -- Qt events ---------------------------------------------------------------

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        """Run the preview only while the page is visible."""
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt override
        """Stop the preview while hidden."""
        super().hideEvent(event)
        self._timer.stop()

    def preview_running(self) -> bool:
        """True while the preview timer runs."""
        return self._timer.isActive()

    # -- presets -----------------------------------------------------------------

    def _label(self) -> str:
        return self.label_edit.text().strip() or self._current.label

    def _show_presets(self) -> None:
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        shown = list(self._presets)
        if advanced_preset_store.find_preset(self._current.key, shown) is None:
            shown.append(self._current)
        for preset in shown:
            current = preset.key == self._current.key
            suffix = UNSAVED_SUFFIX if current and self._dirty else ""
            label = self._current.label if current else preset.label
            self.preset_combo.addItem(f"{label}{suffix}", preset.key)
        self.preset_combo.setCurrentIndex(self.preset_combo.findData(self._current.key))
        self.preset_combo.blockSignals(False)
        self.label_edit.setText(self._current.label)
        self.error_label.setVisible(self._load_error is not None)
        self.error_label.setText(LOAD_FAILED_TEXT.format(error=self._load_error or ""))
        self.delete_button.setEnabled(bool(shown))
        self._show_device()

    def _on_preset_chosen(self, index: int) -> None:
        key = self.preset_combo.itemData(index)
        if key != self._current.key:
            self.select_preset(key)

    def _on_label_edited(self, text: str) -> None:
        if text.strip():
            self._changed(self._current.with_changes(label=text.strip()))

    def _save(self, preset: AdvancedPreset) -> None:
        try:
            preset.validate()
        except PresetError as exc:
            self._report(INVALID_TEXT.format(error=exc))
            return
        presets = [preset if p.key == preset.key else p for p in self._presets]
        if advanced_preset_store.find_preset(preset.key, presets) is None:
            presets.append(preset)
        self._run(lambda: advanced_preset_store.save(presets),
                  lambda _result: self._on_saved(presets, preset),
                  lambda message: self._report(SAVE_FAILED_TEXT.format(error=message)))

    @worker.ignore_deleted
    def _on_saved(self, presets: list[AdvancedPreset], preset: AdvancedPreset) -> None:
        self._presets, self._current, self._dirty = presets, preset, False
        self._load_error = None
        self._show_presets()
        self._update_running()
        self.status.emit(SAVED_TEXT.format(label=preset.label))

    @worker.ignore_deleted
    def _after_delete(self, remaining: list[AdvancedPreset], preset: AdvancedPreset) -> None:
        self._presets = remaining
        self._current = remaining[0] if remaining else _new_preset([])
        self._dirty = False
        self._show_presets()
        if self._runtime_call(lambda rt: rt.active_key()) == preset.key:
            self.stop()
        self.status.emit(DELETED_TEXT.format(label=preset.label))

    @worker.ignore_deleted
    def _on_activated(self, preset: AdvancedPreset, serials: list[str]) -> None:
        if not serials:
            self._report(NOT_CONNECTED_TEXT.format(label=preset.label))
            return
        self._remember(preset.key)
        self.status.emit(ACTIVATED_TEXT.format(label=preset.label, count=len(serials)))

    @worker.ignore_deleted
    def _on_stopped(self) -> None:
        self._remember("")
        self.status.emit(STOPPED_TEXT)

    def _remember(self, key: str) -> None:
        try:
            if self._settings is None:
                self._settings = Settings()
            self._settings.set(LAST_ADVANCED_PRESET, key)
        except OSError as exc:
            self._report(SETTING_FAILED_TEXT.format(error=exc))

    # -- devices and groups ------------------------------------------------------

    def _sync_selectors(self) -> None:
        """Keep selectors of unchanged devices; build new ones, drop gone ones."""
        for serial, selector in list(self._selectors.items()):
            device = self._devices.get(serial)
            if device is None or self._shapes.get(serial) != (device.rows, device.cols):
                self.selector_stack.removeWidget(selector)
                selector.deleteLater()
                del self._selectors[serial]
        for serial, device in self._devices.items():
            if serial not in self._selectors:
                selector = effects_layout.make_selector(device, self.selector_stack)
                selector.selection_changed.connect(self.groups.set_selection)
                self.selector_stack.addWidget(selector)
                self._selectors[serial] = selector
                self._shapes[serial] = (device.rows, device.cols)

    def _program(self, serial: str) -> DeviceProgram:
        program = self._current.program_for(serial)
        return program or DeviceProgram(serial, (), self._devices[serial].name)

    def _show_device(self) -> None:
        serial, selector = self.current_serial(), self.selector()
        if serial is None or selector is None:
            self.selector_stack.setCurrentWidget(self.empty_label)
            self.groups.set_program(None)
            return
        self.selector_stack.setCurrentWidget(selector)
        program = self._program(serial)
        self.groups.set_program(program)
        self.groups.set_selection(selector.selection())
        self._outline(selector, program)

    def _outline(self, selector: KeySelector, program: DeviceProgram) -> None:
        selector.set_group_outlines({g.name: g.leds for g in program.groups})
        self.render_preview()

    def _select_keys(self, cells: frozenset) -> None:
        selector = self.selector()
        if selector is not None:
            selector.set_selection(cells)

    def _on_program_changed(self, program: DeviceProgram) -> None:
        programs = tuple(p for p in self._current.programs if p.serial != program.serial)
        self._changed(self._current.with_changes(programs=programs + (program,)))
        selector = self.selector(program.serial)
        if selector is not None:
            self._outline(selector, program)

    def _changed(self, preset: AdvancedPreset) -> None:
        """Take an edit: mark it unsaved and show it live when it is active."""
        self._current, self._dirty = preset, True
        index = self.preset_combo.findData(preset.key)
        self.preset_combo.setItemText(index, f"{preset.label}{UNSAVED_SUFFIX}")
        self._update_running()

    def _update_running(self) -> None:
        self._runtime_call(lambda rt: rt.update(self._current))

    # -- helpers -----------------------------------------------------------------

    def _runtime_call(self, fn: Callable[[Any], Any]) -> Any:
        """``fn(shared runtime)``; failures are logged and give None."""
        try:
            return fn(advanced_runtime.shared_runtime())
        except Exception:  # a failing runtime must not break editing
            logger.exception("Advanced runtime call failed")
            return None

    def _run(self, fn: Callable[[], Any], on_done: Callable[[Any], None],
             on_error: Callable[[str], None]) -> None:
        """Run ``fn`` through ``worker.run_async``; a failure to start is reported."""
        try:
            worker.run_async(fn, on_done, on_error)
        except Exception as exc:  # never let an exception escape a slot
            logger.exception("Could not start an effects job")
            on_error(str(exc))

    @worker.ignore_deleted
    def _report(self, message: str) -> None:
        logger.warning("Effects: %s", message)
        self.status.emit(message)
