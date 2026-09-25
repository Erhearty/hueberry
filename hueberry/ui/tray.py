# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""System tray icon and menu: show/hide, background and autostart options, quit.

The menu is built even when no tray is available so the controller behaves
the same everywhere; only the QSystemTrayIcon itself is skipped.
"""

import logging
from typing import Callable

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from hueberry import autostart
from hueberry.settings import CLOSE_TO_TRAY, Settings
from hueberry.ui.device_icons import icon_for_type

logger = logging.getLogger(__name__)

TOGGLE_TEXT = "Show/Hide Hueberry"
CLOSE_TO_TRAY_TEXT = "Keep running in the background when closed"
AUTOSTART_TEXT = "Start Hueberry at login"
QUIT_TEXT = "Quit"
TOOLTIP = "Hueberry"
STATUS_PREFIX = "Macros: "
INITIAL_STATUS = "not started"
TRAY_ICON_TYPE = "keyboard"
ACTIVATE_REASONS = (QSystemTrayIcon.ActivationReason.Trigger,
                    QSystemTrayIcon.ActivationReason.DoubleClick)


class TrayController(QObject):
    """Owns the tray icon and menu; emits requests, the owner acts on them.

    ``available`` defaults to ``QSystemTrayIcon.isSystemTrayAvailable()``;
    ``is_autostart_enabled`` / ``set_autostart`` are injectable for tests.
    """

    toggle_window_requested = pyqtSignal()
    quit_requested = pyqtSignal()
    status_message = pyqtSignal(str)

    def __init__(
        self,
        settings: Settings,
        *,
        available: bool | None = None,
        is_autostart_enabled: Callable[[], bool] = autostart.is_enabled,
        set_autostart: Callable[[bool], None] = autostart.set_autostart,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._set_autostart = set_autostart
        self.available = QSystemTrayIcon.isSystemTrayAvailable() if available is None else available
        self._build_menu(is_autostart_enabled)
        self.tray_icon: QSystemTrayIcon | None = None
        if self.available:
            self._build_icon()
        self.set_status(INITIAL_STATUS)

    def _build_menu(self, is_autostart_enabled: Callable[[], bool]) -> None:
        self.menu = QMenu()
        self.toggle_action = QAction(TOGGLE_TEXT, self.menu)
        self.status_action = QAction("", self.menu)
        self.status_action.setEnabled(False)
        self.close_to_tray_action = QAction(CLOSE_TO_TRAY_TEXT, self.menu)
        self.close_to_tray_action.setCheckable(True)
        self.close_to_tray_action.setChecked(self._settings.close_to_tray)
        self.autostart_action = QAction(AUTOSTART_TEXT, self.menu)
        self.autostart_action.setCheckable(True)
        self.autostart_action.setChecked(bool(is_autostart_enabled()))
        self.quit_action = QAction(QUIT_TEXT, self.menu)
        self.menu.addAction(self.toggle_action)
        self.menu.addAction(self.status_action)
        self.menu.addSeparator()
        self.menu.addAction(self.close_to_tray_action)
        self.menu.addAction(self.autostart_action)
        self.menu.addSeparator()
        self.menu.addAction(self.quit_action)
        self.toggle_action.triggered.connect(self.toggle_window_requested)
        self.quit_action.triggered.connect(self.quit_requested)
        self.close_to_tray_action.toggled.connect(self._on_close_to_tray)
        self.autostart_action.toggled.connect(self._on_autostart)

    def _build_icon(self) -> None:
        self.tray_icon = QSystemTrayIcon(icon_for_type(TRAY_ICON_TYPE), self)
        self.tray_icon.setContextMenu(self.menu)
        self.tray_icon.activated.connect(self._on_activated)
        self.tray_icon.show()

    @property
    def close_to_tray(self) -> bool:
        """True when closing the window should only hide it."""
        return self.available and self._settings.close_to_tray

    def set_status(self, text: str) -> None:
        """Show the macro engine state in the menu and tooltip."""
        self.status_action.setText(STATUS_PREFIX + text)
        if self.tray_icon is not None:
            self.tray_icon.setToolTip(f"{TOOLTIP} \u2013 {STATUS_PREFIX}{text}")

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in ACTIVATE_REASONS:
            self.toggle_window_requested.emit()

    def _on_close_to_tray(self, checked: bool) -> None:
        try:
            self._settings.set(CLOSE_TO_TRAY, checked)
        except OSError as exc:
            logger.warning("Saving settings failed: %s", exc)
            self.status_message.emit(f"Could not save settings: {exc}")

    def _on_autostart(self, checked: bool) -> None:
        try:
            self._set_autostart(checked)
        except OSError as exc:  # AutostartError is an OSError
            logger.warning("Changing autostart failed: %s", exc)
            self.autostart_action.blockSignals(True)
            self.autostart_action.setChecked(not checked)
            self.autostart_action.blockSignals(False)
            self.status_message.emit(f"{AUTOSTART_TEXT} failed: {exc}")

    def hide(self) -> None:
        """Remove the icon from the tray (on quit)."""
        if self.tray_icon is not None:
            self.tray_icon.hide()
