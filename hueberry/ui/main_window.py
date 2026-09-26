# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Main window: device cards, per-device page, daemon status bar and empty state.

Blocking service calls go through ``worker.run_async(...)`` looked up on the
:mod:`hueberry.ui.worker` module, so tests can monkeypatch it.
"""

import logging
from functools import partial
from typing import Any, Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QCloseEvent, QKeySequence
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QMainWindow, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from hueberry.backend import animator, lighting_state
from hueberry.backend.daemon import DaemonService
from hueberry.backend.devices import DeviceInfo, describe_device
from hueberry.ui import worker
from hueberry.ui.daemon_panel import DaemonPanel
from hueberry.ui.daemon_status_bar import DaemonStatusBar
from hueberry.ui.device_cards import DeviceGrid
from hueberry.ui.device_page import DevicePage
from hueberry.ui.empty_state import EmptyStatePanel
from hueberry.ui.macros_page import MacrosPage
from hueberry.ui.presets_page import PresetsPage

logger = logging.getLogger(__name__)

WINDOW_TITLE = "Hueberry"
DEFAULT_WIDTH = 900
DEFAULT_HEIGHT = 560
STATUS_TIMEOUT_MS = 8000
REPOLL_TEXT = "Re-scan"
RESTART_TEXT = "Restart daemon"
RESTART_SHORTCUT = "Ctrl+Shift+R"
DAEMON_DIALOG_TITLE = "OpenRazer daemon"
NO_DEVICES_TEXT = "The OpenRazer daemon reports no devices."
NOT_CONNECTED_TEXT = "Not connected to the OpenRazer daemon."
UNKNOWN_ERROR = "unknown error"
MACROS_TEXT = "&Macros\u2026"
MACROS_SHORTCUT = "Ctrl+M"
MACROS_TIP = "Record, edit and bind macros (Ctrl+M)"
PRESETS_TEXT = "Presets\u2026"  # no mnemonic: every letter is taken; Ctrl+P opens it
PRESETS_SHORTCUT = "Ctrl+P"
PRESETS_TIP = "Create, edit and apply lighting presets (Ctrl+P)"


class MainWindow(QMainWindow):
    """Top-level window: a home grid of device cards and a page per device.

    The daemon status bar (Restart / Re-scan / Daemon…) is always visible; the
    Daemon… button opens the :class:`DaemonPanel` in a non-modal dialog.
    With a ``tray`` whose close-to-tray option is on, closing only hides the
    window; otherwise it emits ``quit_requested`` (when a tray is given).
    """

    quit_requested = pyqtSignal()

    def __init__(self, service: DaemonService, engine: Any = None, tray: Any = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._engine = engine
        self._tray = tray
        self._entries: list[tuple[Any, DeviceInfo]] = []
        self._last_serial: str | None = None  # last opened device, kept across reloads
        self._current_serial: str | None = None  # selected device, if it is present
        self._busy = False  # a window action (status bar / shortcut / empty state) is running
        self._panel_busy = False  # a Daemon dialog action is running
        self._before_presets: QWidget | None = None  # page to return to from Presets
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT)
        self._build_pages()
        self._build_daemon_dialog()
        self._build_actions()
        self.macros_button = QPushButton(MACROS_TEXT, self)
        self.macros_button.setToolTip(MACROS_TIP)
        self.statusBar().addPermanentWidget(self.macros_button)
        self.presets_button = QPushButton(PRESETS_TEXT, self)
        self.presets_button.setToolTip(PRESETS_TIP)
        self.statusBar().addPermanentWidget(self.presets_button)
        self.daemon_bar = DaemonStatusBar(self._service, self)
        self.statusBar().addPermanentWidget(self.daemon_bar)
        self._connect_signals()
        self.reload()

    # -- construction --------------------------------------------------------

    def _build_pages(self) -> None:
        self.home_page = DeviceGrid(self)
        self.device_page = DevicePage(self)
        self.tabs = self.device_page.tabs
        self.info_panel = self.device_page.info_panel
        self.lighting_panel = self.device_page.lighting_panel
        self.mouse_page = self.device_page.mouse_page
        self.mouse_panel = self.device_page.mouse_panel
        self.empty_page = EmptyStatePanel(self)
        self.macros_page = MacrosPage(self._engine, self)
        self.presets_page = PresetsPage(self)
        self.stack = QStackedWidget(self)
        for page in (self.home_page, self.device_page, self.empty_page, self.macros_page,
                     self.presets_page):
            self.stack.addWidget(page)
        self.setCentralWidget(self.stack)

    def _build_daemon_dialog(self) -> None:
        self.daemon_dialog = QDialog(self)
        self.daemon_dialog.setWindowTitle(DAEMON_DIALOG_TITLE)
        self.daemon_dialog.setModal(False)
        self.daemon_panel = DaemonPanel(self._service, self.daemon_dialog)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self.daemon_dialog)
        buttons.rejected.connect(self.daemon_dialog.close)
        layout = QVBoxLayout(self.daemon_dialog)
        layout.addWidget(self.daemon_panel)
        layout.addWidget(buttons)

    def _build_actions(self) -> None:
        self.repoll_action = QAction(REPOLL_TEXT, self)
        self.repoll_action.setShortcut(QKeySequence(QKeySequence.StandardKey.Refresh))
        self.restart_action = QAction(RESTART_TEXT, self)
        self.restart_action.setShortcut(QKeySequence(RESTART_SHORTCUT))
        self.macros_action = QAction(MACROS_TEXT, self)
        self.macros_action.setShortcut(QKeySequence(MACROS_SHORTCUT))
        self.presets_action = QAction(PRESETS_TEXT, self)
        self.presets_action.setShortcut(QKeySequence(PRESETS_SHORTCUT))
        for action in (self.repoll_action, self.restart_action, self.macros_action,
                       self.presets_action):
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            self.addAction(action)

    def _connect_signals(self) -> None:
        service = self._service
        self.repoll_action.triggered.connect(self._rescan)
        self.restart_action.triggered.connect(self._restart_daemon)
        self.daemon_bar.rescan_requested.connect(self._rescan)
        self.daemon_bar.restart_requested.connect(self._restart_daemon)
        self.daemon_bar.details_requested.connect(self._show_daemon_dialog)
        self.home_page.device_activated.connect(self._on_device_activated)
        self.device_page.back_requested.connect(self._go_home)
        self.empty_page.retry_requested.connect(
            lambda: self.run_service_action("Retry", service.repoll))
        self.empty_page.start_requested.connect(
            lambda: self.run_service_action("Start daemon", service.start_and_connect))
        for panel in (self.lighting_panel, self.mouse_panel, self.daemon_panel):
            panel.status.connect(self.show_status)
        self.lighting_panel.report_preset_error()  # loaded before status was connected
        self.daemon_panel.daemon_changed.connect(self.reload)
        self.daemon_panel.busy_changed.connect(self._on_panel_busy)
        self._connect_macros()
        self._connect_presets()

    def _connect_presets(self) -> None:
        self.presets_action.triggered.connect(self.show_presets)
        self.presets_button.clicked.connect(self.show_presets)
        self.presets_page.back_requested.connect(self._leave_presets)
        self.presets_page.status.connect(self.show_status)
        self.presets_page.presets_saved.connect(self.lighting_panel.reload_presets)

    def _connect_macros(self) -> None:
        self.macros_action.triggered.connect(self.show_macros)
        self.macros_button.clicked.connect(self.show_macros)
        self.macros_page.back_requested.connect(self._leave_macros)
        self.macros_page.status.connect(self.show_status)
        if self._tray is not None:
            self.macros_page.engine_summary.connect(self._tray.set_status)
            self._tray.toggle_window_requested.connect(self.toggle_visible)
            self._tray.status_message.connect(self.show_status)

    # -- public API ----------------------------------------------------------

    def show_status(self, message: str) -> None:
        """Show ``message`` in the status bar."""
        self.statusBar().showMessage(message, STATUS_TIMEOUT_MS)

    def selected_serial(self) -> str | None:
        """Serial of the selected device, or None."""
        return self._current_serial

    def reload(self) -> None:
        """Re-read the devices from the service, keeping the selected serial."""
        try:
            self._reload()
        except Exception as exc:  # never let an exception escape a slot
            logger.exception("Reloading devices failed")
            self.show_status(f"Error: {exc}")

    def run_service_action(self, label: str, fn: Callable[[], Any]) -> None:
        """Run a blocking service call in the background, then reload.

        Refused while any service action (window or Daemon dialog) is running.
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

    def show_macros(self) -> None:
        """Open the Macros page with fresh engine state."""
        self.macros_page.refresh()
        self.stack.setCurrentWidget(self.macros_page)
        self.macros_page.device_list.setFocus()

    def show_presets(self) -> None:
        """Open the Presets page, remembering the page to return to."""
        current = self.stack.currentWidget()
        if current is not self.presets_page:
            self._before_presets = current
        self.presets_page.refresh()
        self.stack.setCurrentWidget(self.presets_page)
        self.presets_page.preset_list.setFocus()

    def start_engine(self) -> None:
        """Start the macro engine in the background (no-op without an engine)."""
        self.macros_page.start_engine()

    def show_and_raise(self) -> None:
        """Show the window (e.g. from the tray or a second launch) and bring it forward."""
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def toggle_visible(self) -> None:
        """Hide a visible window, show a hidden or minimised one."""
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.show_and_raise()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        """Hide to the tray when enabled; otherwise close (and quit, with a tray)."""
        if self._tray is not None and self._tray.close_to_tray:
            event.ignore()
            self.hide()
            self.show_status("Hueberry keeps running in the tray")
            return
        event.accept()
        if self._tray is not None:
            self.quit_requested.emit()

    # -- internals -----------------------------------------------------------

    def _leave_macros(self) -> None:
        self.stack.setCurrentWidget(self.home_page)
        self.reload()
        if self.stack.currentWidget() is self.home_page:
            self.home_page.focus_selected()

    def _leave_presets(self) -> None:
        """Return to the page shown before Presets, then reload (it may be stale)."""
        previous = self._before_presets or self.home_page
        self._before_presets = None
        self.stack.setCurrentWidget(previous)
        self.reload()
        if self.stack.currentWidget() is self.home_page:
            self.home_page.focus_selected()

    def _rescan(self) -> None:
        self.run_service_action(REPOLL_TEXT, self._service.repoll)

    def _restart_daemon(self) -> None:
        self.run_service_action(RESTART_TEXT, self._service.restart)

    def _show_daemon_dialog(self) -> None:
        self.daemon_panel.refresh()
        self.daemon_dialog.show()
        self.daemon_dialog.raise_()
        self.daemon_dialog.activateWindow()

    def _reload(self) -> None:
        devices = self._service.devices if self._service.connected else []
        self._refresh_animations(devices)
        self.daemon_panel.refresh()
        self.daemon_bar.refresh()
        self._entries = [(dev, describe_device(dev)) for dev in devices]
        self.home_page.set_devices([info for _dev, info in self._entries])
        self.presets_page.set_devices(self._entries)
        if self.stack.currentWidget() in (self.macros_page, self.presets_page):
            return  # stay on the Macros page; the grid is updated for later
        if not self._entries:
            self._show_empty()
            return
        on_device_page = self.stack.currentWidget() is self.device_page
        if on_device_page and self._entry_for(self._last_serial) is not None:
            self._open_device(self._last_serial)
        else:
            self._show_home()

    def _refresh_animations(self, devices: list[Any]) -> None:
        """Rebind preset animations to the new device objects, then restore saved ones."""
        try:
            animator.shared_animator().refresh(devices)
            error = lighting_state.shared_lighting_state().restore(devices)
            if error:
                self.show_status(f"Lighting state: {error}")
        except Exception as exc:  # a failing animator must not break the reload
            logger.exception("Refreshing lighting animations failed")
            self.show_status(f"Animation error: {exc}")

    def _entry_for(self, serial: str | None) -> tuple[Any, DeviceInfo] | None:
        for dev, info in self._entries:
            if info.serial == serial:
                return dev, info
        return None

    def _show_empty(self) -> None:
        if self._service.connected:
            message = NO_DEVICES_TEXT
        else:
            message = self._service.last_error or NOT_CONNECTED_TEXT
        self.empty_page.set_message(message)
        self.empty_page.set_can_start(not self._service.connected)
        self._current_serial = None
        self.device_page.set_device(None, None)
        self.stack.setCurrentWidget(self.empty_page)

    def _show_home(self) -> None:
        present = self._entry_for(self._last_serial) is not None
        self._current_serial = self._last_serial if present else None
        self.home_page.select_serial(self._current_serial)
        self.device_page.set_device(None, None)
        self.stack.setCurrentWidget(self.home_page)

    def _go_home(self) -> None:
        """User navigation back to the home grid: focus the selected card."""
        self._show_home()
        self.home_page.focus_selected()

    def _on_device_activated(self, serial: str) -> None:
        """User activated a card: open its device page and focus the tabs."""
        try:
            self._open_device(serial)
            if self.stack.currentWidget() is self.device_page:
                self.tabs.setFocus()
        except Exception as exc:  # never let an exception escape a slot
            logger.exception("Showing device failed")
            self.show_status(f"Error: {exc}")

    def _open_device(self, serial: str | None) -> None:
        entry = self._entry_for(serial)
        if entry is None:
            return
        dev, info = entry
        self._last_serial = self._current_serial = info.serial
        self.home_page.select_serial(info.serial)
        self.device_page.set_device(dev, info)
        self.stack.setCurrentWidget(self.device_page)

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
        self.daemon_bar.set_busy(blocked)
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
