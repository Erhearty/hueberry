# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Macros page: input devices with their engine state, their macros, and a banner.

Macros are edited on an in-memory :class:`MacroConfig` and written to
macros.json by *Save*, after which the running engine is asked to reload.
Editing works while the engine is down; engine calls go through
``worker.run_async`` (looked up on the module) so tests can run them inline.
"""

import logging
import uuid
from typing import Any

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from hueberry.backend import macro_engine as engine_states
from hueberry.macros import keycodes, store
from hueberry.macros.model import DeviceMacros, Macro, MacroConfig, ModelError
from hueberry.ui import theme, worker
from hueberry.ui.macro_editor import MacroEditorDialog
from hueberry.ui.macros_banner import BANNER_STARTING, banner_text, state_label

__all__ = ["MacrosPage", "banner_text", "state_label"]

logger = logging.getLogger(__name__)

TITLE_TEXT = "<b>Macros</b>"
BACK_TEXT = "\u2190 Devices"
DEFAULT_TRIGGER = "BTN_SIDE"
NEW_MACRO_NAME = "New macro"
DEVICE_ROLE = Qt.ItemDataRole.UserRole
NOT_CONNECTED_LABEL = "not connected"
START_ENGINE_TEXT = "Start &engine"
SUMMARY_RUNNING = "running, {count} grabbed"
SUMMARY_TEXTS = {engine_states.STATE_EVDEV_MISSING: "python-evdev missing",
                 engine_states.STATE_STARTING: "starting"}
SUMMARY_DOWN = "not running"
SAVED_TEXT = "Macros saved"
SAVED_RELOADED_TEXT = "Macros saved and applied"
SAVED_OFFLINE_TEXT = "Macros saved; they apply once the macro engine runs"
ENGINE_POLL_MS = 5000  # how often a crashed/stopped engine is noticed (poll() is a cheap waitpid)


class MacrosPage(QWidget):
    """Device list, macro list, editor launch, Save; emits ``status`` messages."""

    status = pyqtSignal(str)
    back_requested = pyqtSignal()
    engine_summary = pyqtSignal(str)

    def __init__(self, engine: Any = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._devices: dict[str, dict] = {}  # identity -> {name, state, error, present}
        self._permissions: dict = {}
        self._engine_config_error: str | None = None
        self._dirty = False
        self._starting = False  # a start_engine() call is in flight
        self._polled_state: str | None = None  # engine state seen by the last _poll_engine()
        self.editor: MacroEditorDialog | None = None
        self.config, self._load_error = store.load()
        self._build_widgets()
        self._build_layout()
        self._connect_signals()
        self._show_devices()
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(ENGINE_POLL_MS)
        self.poll_timer.timeout.connect(self._poll_engine)
        if engine is not None:
            self.poll_timer.start()

    # -- construction --------------------------------------------------------

    def _build_widgets(self) -> None:
        self.back_button = QPushButton(BACK_TEXT, self)
        self.title_label = QLabel(TITLE_TEXT, self)
        self.banner_label = QLabel(self)
        self.banner_label.setWordWrap(True)
        self.banner_label.setAccessibleName("Macro engine status")
        self.banner_label.setStyleSheet(f"color: {theme.ERROR};")
        self.start_button = QPushButton(START_ENGINE_TEXT, self)
        self.device_list = QListWidget(self)
        self.device_list.setAccessibleName("Input devices")
        self.macro_list = QListWidget(self)
        self.macro_list.setAccessibleName("Macros of the selected device")
        self.add_button = QPushButton("&Add\u2026", self)
        self.edit_button = QPushButton("&Edit\u2026", self)
        self.delete_button = QPushButton("&Delete", self)
        self.save_button = QPushButton("&Save", self)
        self.refresh_button = QPushButton("Re&load", self)
        self.refresh_button.setToolTip("Re-read device states from the macro engine")

    def _build_layout(self) -> None:
        header = QHBoxLayout()
        for widget in (self.back_button, self.title_label):
            header.addWidget(widget)
        header.addStretch(1)
        header.addWidget(self.refresh_button)
        banner = QHBoxLayout()
        banner.addWidget(self.banner_label, 1)
        banner.addWidget(self.start_button)
        buttons = QVBoxLayout()
        for button in (self.add_button, self.edit_button, self.delete_button, self.save_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        lists = QHBoxLayout()
        lists.addWidget(self.device_list, 1)
        lists.addWidget(self.macro_list, 1)
        lists.addLayout(buttons)
        outer = QVBoxLayout(self)
        outer.addLayout(header)
        outer.addLayout(banner)
        outer.addLayout(lists, 1)

    def _connect_signals(self) -> None:
        self.back_button.clicked.connect(self.back_requested)
        self.refresh_button.clicked.connect(self.refresh)
        self.start_button.clicked.connect(self.start_engine)
        self.device_list.currentRowChanged.connect(lambda _row: self._show_macros())
        self.macro_list.currentRowChanged.connect(lambda _row: self._update_buttons())
        self.macro_list.itemChanged.connect(self._on_macro_toggled)
        self.macro_list.itemActivated.connect(lambda _item: self._edit_macro())
        self.add_button.clicked.connect(self._add_macro)
        self.edit_button.clicked.connect(self._edit_macro)
        self.delete_button.clicked.connect(self._delete_macro)
        self.save_button.clicked.connect(self.save)

    # -- public API ----------------------------------------------------------

    def selected_identity(self) -> str | None:
        """Identity of the selected device, or None."""
        item = self.device_list.currentItem()
        return item.data(DEVICE_ROLE) if item is not None else None

    def refresh(self) -> None:
        """Re-read device states from the engine (or show config devices when it is down)."""
        if not self._dirty:
            self.config, self._load_error = store.load()
        if self._engine is None or self._engine.poll() != engine_states.STATE_RUNNING:
            self._apply_engine_data(None)
            return
        engine = self._engine
        worker.run_async(lambda: (engine.list_devices(), engine.status()),
                         self._apply_engine_data, self._on_fetch_failed)

    def start_engine(self) -> None:
        """Start the macro engine in the background, then refresh."""
        if self._engine is None:
            return
        self._starting = True
        self._update_banner()
        # Spawn on the GUI thread: the engine sets PR_SET_PDEATHSIG, which fires when the
        # *thread* that forked it exits, and QThreadPool threads expire after 30 s idle.
        # Only the blocking readiness wait may run on a pool worker.
        if not self._engine.spawn():
            self._on_start_failed(self._engine.last_error or engine_states.STATE_CRASHED)
            return
        worker.run_async(self._engine.wait_ready, self._on_started, self._on_start_failed)

    def save(self) -> bool:
        """Write macros.json, then ask a running engine to reload it."""
        try:
            store.save(self.config)
        except (ModelError, OSError) as exc:
            logger.warning("Saving macros failed: %s", exc)
            self.status.emit(f"Saving macros failed: {exc}")
            return False
        self._dirty = False
        self._load_error = None
        if self._engine is None or self._engine.poll() != engine_states.STATE_RUNNING:
            self.status.emit(SAVED_OFFLINE_TEXT)
            self._update_banner()
            return True
        self.status.emit(SAVED_TEXT)
        worker.run_async(self._engine.reload, self._on_reloaded, self._on_fetch_failed)
        return True

    # -- engine data ---------------------------------------------------------

    @worker.ignore_deleted
    def _apply_engine_data(self, data: Any) -> None:
        listed, status = data if data is not None else ({}, {})
        self._permissions = listed.get("permissions") or {}
        self._engine_config_error = status.get("config_error")
        devices: dict[str, dict] = {}
        for entry in listed.get("devices", []):
            if entry.get("has_keys", True):
                devices[entry["identity"]] = {"name": entry.get("name", ""), "state": entry.get("state"),
                                              "error": None, "present": True}
        for entry in status.get("devices", []):
            known = devices.setdefault(entry["identity"], {"name": entry.get("name", ""), "present": False})
            known.update(state=entry.get("state"), error=entry.get("error"))
        self._devices = devices
        self._show_devices()

    @worker.ignore_deleted
    def _on_fetch_failed(self, message: str) -> None:
        logger.warning("Macro engine request failed: %s", message)
        self.status.emit(f"Macro engine: {message}")
        self._apply_engine_data(None)

    @worker.ignore_deleted
    def _on_started(self, _ok: Any) -> None:
        self._starting = False
        self.refresh()

    @worker.ignore_deleted
    def _on_start_failed(self, message: str) -> None:
        self._starting = False
        self._on_fetch_failed(message)

    def _poll_engine(self) -> None:
        """Timer slot: notice a crashed/stopped engine and update banner and tray summary.

        ``engine.poll()`` only checks the child's return code (no IPC), so it runs here.
        """
        if self._engine is None or self._starting:
            return  # the readiness wait owns the state while starting
        state = self._engine.poll()
        if state != self._polled_state:
            self._polled_state = state
            self.refresh()

    @worker.ignore_deleted
    def _on_reloaded(self, _status: Any) -> None:
        self.status.emit(SAVED_RELOADED_TEXT)
        self.refresh()

    # -- device and macro lists ----------------------------------------------

    def _rows(self) -> list[tuple[str, str, str]]:
        rows = {}
        for identity, info in self._devices.items():
            label = state_label(info.get("state")) if info.get("present") or info.get("state") \
                else NOT_CONNECTED_LABEL
            rows[identity] = (info.get("name") or identity, label)
        for device in self.config.devices:
            rows.setdefault(device.identity, (device.name or device.identity, NOT_CONNECTED_LABEL))
        return sorted(((identity, name, label) for identity, (name, label) in rows.items()),
                      key=lambda row: row[1].lower())

    def _show_devices(self) -> None:
        selected = self.selected_identity()
        self.device_list.blockSignals(True)
        self.device_list.clear()
        for identity, name, label in self._rows():
            item = QListWidgetItem(f"{name} \u2013 {label}", self.device_list)
            item.setData(DEVICE_ROLE, identity)
            error = self._devices.get(identity, {}).get("error")
            item.setToolTip(f"{identity}\n{error}" if error else identity)
            if identity == selected:
                self.device_list.setCurrentItem(item)
        if self.device_list.currentRow() < 0 and self.device_list.count():
            self.device_list.setCurrentRow(0)
        self.device_list.blockSignals(False)
        self._show_macros()
        self._update_banner()

    def _device_macros(self, create: bool = False) -> DeviceMacros | None:
        identity = self.selected_identity()
        if identity is None:
            return None
        device = self.config.for_device(identity)
        if device is None and create:
            name = self._devices.get(identity, {}).get("name", "")
            device = DeviceMacros(identity=identity, name=name)
            self.config.devices.append(device)
        return device

    def _show_macros(self, select: int = -1) -> None:
        device = self._device_macros()
        self.macro_list.blockSignals(True)
        self.macro_list.clear()
        for macro in device.macros if device is not None else []:
            item = QListWidgetItem(f"{macro.name} ({keycodes.display_name(macro.trigger)})",
                                   self.macro_list)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if macro.enabled else Qt.CheckState.Unchecked)
        if 0 <= select < self.macro_list.count():
            self.macro_list.setCurrentRow(select)
        self.macro_list.blockSignals(False)
        self._update_buttons()

    def _update_buttons(self) -> None:
        has_device = self.selected_identity() is not None
        has_macro = has_device and self.macro_list.currentRow() >= 0
        self.add_button.setEnabled(has_device)
        self.edit_button.setEnabled(has_macro)
        self.delete_button.setEnabled(has_macro)
        self.save_button.setEnabled(self._dirty)

    def _update_banner(self) -> None:
        config_error = self._load_error or self._engine_config_error
        if self._starting:
            banner: tuple[str, bool] | None = (BANNER_STARTING, False)
        else:
            banner = banner_text(self._engine, self._permissions, config_error)
        self.banner_label.setVisible(banner is not None)
        self.banner_label.setText(banner[0] if banner else "")
        self.start_button.setVisible(bool(banner and banner[1]))
        self.engine_summary.emit(self._summary())

    def _summary(self) -> str:
        state = self._engine.state if self._engine is not None else None
        if self._starting:
            state = engine_states.STATE_STARTING
        if state == engine_states.STATE_RUNNING:
            grabbed = sum(1 for info in self._devices.values() if info.get("state") == "active")
            return SUMMARY_RUNNING.format(count=grabbed)
        return SUMMARY_TEXTS.get(state, SUMMARY_DOWN)

    def _mark_dirty(self) -> None:
        self._dirty = True
        self._update_buttons()

    # -- editing -------------------------------------------------------------

    def _on_macro_toggled(self, item: QListWidgetItem) -> None:
        device = self._device_macros()
        row = self.macro_list.row(item)
        if device is not None and 0 <= row < len(device.macros):
            device.macros[row].enabled = item.checkState() == Qt.CheckState.Checked
            self._mark_dirty()

    def _add_macro(self) -> None:
        macro = Macro(id=uuid.uuid4().hex, name=NEW_MACRO_NAME, enabled=True,
                      trigger=DEFAULT_TRIGGER, steps=[])
        self._open_editor(macro, None)

    def _edit_macro(self) -> None:
        device = self._device_macros()
        row = self.macro_list.currentRow()
        if device is not None and 0 <= row < len(device.macros):
            self._open_editor(device.macros[row], row)

    def _open_editor(self, macro: Macro, row: int | None) -> None:
        identity = self.selected_identity()
        device = self._device_macros()
        others = [m.trigger for i, m in enumerate(device.macros if device else []) if i != row]
        present = self._devices.get(identity, {}).get("present", False)
        running = self._engine is not None and self._engine.state == engine_states.STATE_RUNNING
        self.editor = MacroEditorDialog(macro, engine=self._engine if running and present else None,
                                        identity=identity, taken_triggers=others, parent=self)
        self.editor.accepted.connect(lambda dialog=self.editor: self._editor_done(dialog, row))
        self.editor.open()

    def _editor_done(self, dialog: MacroEditorDialog, row: int | None) -> None:
        device = self._device_macros(create=True)
        if device is None:
            return
        if row is None:
            device.macros.append(dialog.macro())
            row = len(device.macros) - 1
        else:
            device.macros[row] = dialog.macro()
        self._show_macros(row)
        self._mark_dirty()

    def _delete_macro(self) -> None:
        device = self._device_macros()
        row = self.macro_list.currentRow()
        if device is not None and 0 <= row < len(device.macros):
            del device.macros[row]
            self._show_macros(min(row, len(device.macros) - 1))
            self._mark_dirty()
