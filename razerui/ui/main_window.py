# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 RazerUI contributors
"""Main window: device list, per-device tabs, toolbar, status bar and empty state.

Blocking service calls go through ``worker.run_async(...)`` looked up on the
:mod:`razerui.ui.worker` module, so tests can monkeypatch it.
"""

import logging
from functools import partial
from typing import Any, Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QLabel, QListWidget, QListWidgetItem, QMainWindow, QSplitter, QStackedWidget, QTabWidget,
    QVBoxLayout, QWidget,
)

from razerui.backend.daemon import DaemonService
from razerui.backend.devices import DeviceInfo, describe_device
from razerui.ui import worker
from razerui.ui.daemon_panel import DaemonPanel
from razerui.ui.device_info_panel import DeviceInfoPanel
from razerui.ui.empty_state import EmptyStatePanel
from razerui.ui.lighting_panel import LightingPanel
from razerui.ui.mouse_panel import MousePanel

logger = logging.getLogger(__name__)

WINDOW_TITLE = "RazerUI"
DEFAULT_WIDTH = 900
DEFAULT_HEIGHT = 560
LIST_MIN_WIDTH = 220
SERIAL_ROLE = Qt.ItemDataRole.UserRole
NO_ROW = -1
FIRST_ROW = 0
MOUSE_TAB_INDEX = 2
STATUS_TIMEOUT_MS = 8000
DEVICES_LABEL = "Devi&ces:"
TAB_INFO = "&Info"
TAB_LIGHTING = "Li&ghting"
TAB_MOUSE = "Mo&use"
TAB_DAEMON = "Daemo&n"
REPOLL_TEXT = "Repoll"
RESTART_TEXT = "Restart daemon"
RESTART_SHORTCUT = "Ctrl+Shift+R"
NO_DEVICES_TEXT = "The OpenRazer daemon reports no devices."
NOT_CONNECTED_TEXT = "Not connected to the OpenRazer daemon."
UNKNOWN_ERROR = "unknown error"


class MainWindow(QMainWindow):
    """Top-level window listing devices and hosting the Info/Lighting/Mouse/Daemon tabs."""

    def __init__(self, service: DaemonService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._entries: list[tuple[Any, DeviceInfo]] = []
        self._last_serial: str | None = None
        self._busy = False  # a window action (toolbar / empty state) is running
        self._panel_busy = False  # a Daemon-tab action is running
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT)
        self._build_panels()
        self._build_central()
        self._build_toolbar()
        self._connect_signals()
        self.reload()

    # -- construction --------------------------------------------------------

    def _build_panels(self) -> None:
        self.device_list = QListWidget(self)
        self.device_list.setMinimumWidth(LIST_MIN_WIDTH)
        self.device_list.setAccessibleName("Devices")
        self.info_panel = DeviceInfoPanel(self)
        self.lighting_panel = LightingPanel(self)
        self.mouse_page = QWidget(self)
        self.mouse_panel = MousePanel(self.mouse_page)
        QVBoxLayout(self.mouse_page).addWidget(self.mouse_panel)
        self.daemon_panel = DaemonPanel(self._service, self)
        self.empty_page = EmptyStatePanel(self)

    def _build_central(self) -> None:
        self.tabs = QTabWidget(self)
        self.tabs.addTab(self.info_panel, TAB_INFO)
        self.tabs.addTab(self.lighting_panel, TAB_LIGHTING)
        self.tabs.addTab(self.mouse_page, TAB_MOUSE)
        self.tabs.addTab(self.daemon_panel, TAB_DAEMON)
        left = QWidget(self)
        label = QLabel(DEVICES_LABEL, left)
        label.setBuddy(self.device_list)
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(label)
        left_layout.addWidget(self.device_list)
        self.devices_page = QSplitter(Qt.Orientation.Horizontal, self)
        self.devices_page.addWidget(left)
        self.devices_page.addWidget(self.tabs)
        self.devices_page.setStretchFactor(1, 1)
        self.stack = QStackedWidget(self)
        self.stack.addWidget(self.devices_page)
        self.stack.addWidget(self.empty_page)
        self.setCentralWidget(self.stack)
        QWidget.setTabOrder(self.device_list, self.tabs)

    def _build_toolbar(self) -> None:
        toolbar = self.addToolBar("Main")
        toolbar.setObjectName("main_toolbar")
        self.repoll_action = QAction(REPOLL_TEXT, self)
        self.repoll_action.setShortcut(QKeySequence(QKeySequence.StandardKey.Refresh))
        self.restart_action = QAction(RESTART_TEXT, self)
        self.restart_action.setShortcut(QKeySequence(RESTART_SHORTCUT))
        for action in (self.repoll_action, self.restart_action):
            shortcut = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
            action.setToolTip(f"{action.text()} ({shortcut})" if shortcut else action.text())
            toolbar.addAction(action)

    def _connect_signals(self) -> None:
        service = self._service
        self.device_list.currentRowChanged.connect(self._on_row_changed)
        self.repoll_action.triggered.connect(
            lambda: self.run_service_action(REPOLL_TEXT, service.repoll))
        self.restart_action.triggered.connect(
            lambda: self.run_service_action(RESTART_TEXT, service.restart))
        self.empty_page.retry_requested.connect(
            lambda: self.run_service_action("Retry", service.repoll))
        self.empty_page.start_requested.connect(
            lambda: self.run_service_action("Start daemon", service.start_and_connect))
        for panel in (self.lighting_panel, self.mouse_panel, self.daemon_panel):
            panel.status.connect(self.show_status)
        self.daemon_panel.daemon_changed.connect(self.reload)
        self.daemon_panel.busy_changed.connect(self._on_panel_busy)

    # -- public API ----------------------------------------------------------

    def show_status(self, message: str) -> None:
        """Show ``message`` in the status bar."""
        self.statusBar().showMessage(message, STATUS_TIMEOUT_MS)

    def selected_serial(self) -> str | None:
        """Serial of the selected device, or None."""
        item = self.device_list.currentItem()
        return item.data(SERIAL_ROLE) if item is not None else None

    def reload(self) -> None:
        """Re-read the device list from the service, keeping the selected serial."""
        try:
            self._reload()
        except Exception as exc:  # never let an exception escape a slot
            logger.exception("Reloading devices failed")
            self.show_status(f"Error: {exc}")

    def run_service_action(self, label: str, fn: Callable[[], Any]) -> None:
        """Run a blocking service call in the background, then reload.

        Refused while any service action (window or Daemon tab) is running.
        """
        if self._busy or self._panel_busy:
            self.show_status(f"{label}: another action is still running")
            return
        self._set_busy(True)
        self.show_status(f"{label}\u2026")
        try:
            worker.run_async(fn, partial(self._on_action_done, label),
                             partial(self._on_action_failed, label))
        except Exception as exc:  # never let an exception escape a slot
            logger.exception("Could not start %s", label)
            self._on_action_failed(label, str(exc))

    # -- internals -----------------------------------------------------------

    def _reload(self) -> None:
        devices = self._service.devices if self._service.connected else []
        self.daemon_panel.refresh()
        self._fill_list(devices)
        if not self._entries:
            self._show_empty()
            return
        self.stack.setCurrentWidget(self.devices_page)
        row = self._row_for_serial(self._last_serial)
        self.device_list.blockSignals(True)
        self.device_list.setCurrentRow(row)
        self.device_list.blockSignals(False)
        self._show_device(row)

    def _fill_list(self, devices: list) -> None:
        self._entries = [(dev, describe_device(dev)) for dev in devices]
        self.device_list.blockSignals(True)
        self.device_list.clear()
        for _dev, info in self._entries:
            item = QListWidgetItem(f"{info.name} ({info.type})")
            item.setToolTip(info.serial)
            item.setData(SERIAL_ROLE, info.serial)
            self.device_list.addItem(item)
        self.device_list.blockSignals(False)

    def _row_for_serial(self, serial: str | None) -> int:
        for row, (_dev, info) in enumerate(self._entries):
            if info.serial == serial:
                return row
        return FIRST_ROW

    def _show_empty(self) -> None:
        if self._service.connected:
            message = NO_DEVICES_TEXT
        else:
            message = self._service.last_error or NOT_CONNECTED_TEXT
        self.empty_page.set_message(message)
        self.empty_page.set_can_start(not self._service.connected)
        self.stack.setCurrentWidget(self.empty_page)
        self._show_device(NO_ROW)

    def _on_row_changed(self, row: int) -> None:
        try:
            self._show_device(row)
        except Exception as exc:  # never let an exception escape a slot
            logger.exception("Showing device failed")
            self.show_status(f"Error: {exc}")

    def _show_device(self, row: int) -> None:
        dev, info = self._entries[row] if 0 <= row < len(self._entries) else (None, None)
        if info is not None:
            self._last_serial = info.serial
        is_mouse = info is not None and info.is_mouse
        self.info_panel.set_device(info)
        self.lighting_panel.set_device(dev)
        self.mouse_panel.set_device(dev if is_mouse else None)
        self._set_mouse_tab(is_mouse)

    def _set_mouse_tab(self, present: bool) -> None:
        index = self.tabs.indexOf(self.mouse_page)
        if present and index < 0:
            self.tabs.insertTab(MOUSE_TAB_INDEX, self.mouse_page, TAB_MOUSE)
        elif not present and index >= 0:
            self.tabs.removeTab(index)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.daemon_panel.set_external_busy(busy)
        self._update_actions()

    def _on_panel_busy(self, busy: bool) -> None:
        self._panel_busy = busy
        self._update_actions()

    def _update_actions(self) -> None:
        blocked = self._busy or self._panel_busy
        self.repoll_action.setEnabled(not blocked)
        self.restart_action.setEnabled(not blocked)
        self.empty_page.set_busy(blocked)

    def _on_action_done(self, label: str, ok: Any) -> None:
        if ok:
            self.show_status(f"{label}: done")
        else:
            reason = self._service.last_error or UNKNOWN_ERROR
            self.show_status(f"{label} failed: {reason}")
        self._set_busy(False)
        self.reload()

    def _on_action_failed(self, label: str, message: str) -> None:
        logger.warning("%s failed: %s", label, message)
        self.show_status(f"{label} failed: {message}")
        self._set_busy(False)
        self.reload()
