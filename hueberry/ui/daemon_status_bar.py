# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Permanent status-bar widget: daemon state plus Restart, Re-scan and Daemon… buttons.

The buttons only emit signals; the owner decides what to run.
"""

import logging

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from hueberry.backend.daemon import DaemonService, DaemonStatus
from hueberry.ui import theme

logger = logging.getLogger(__name__)

CONNECTED_TEXT = "Connected"
RUNNING_TEXT = "Daemon running"
STOPPED_TEXT = "Daemon not running"
RESTART_TEXT = "Restart"
RESCAN_TEXT = "Re-scan"
DETAILS_TEXT = "Daemon\u2026"
RESTART_TIP = "Restart the OpenRazer daemon and reconnect"
RESCAN_TIP = "Reconnect and re-read the device list"
DETAILS_TIP = "Show daemon details and settings"
CONNECTED_COLOUR = theme.ACCENT
RUNNING_COLOUR = theme.TEXT_MUTED
STOPPED_COLOUR = theme.ERROR
DOT_SIZE = 10
DOT_RADIUS = DOT_SIZE // 2


def describe_status(connected: bool, status: DaemonStatus) -> tuple[str, str]:
    """Return the (label text, dot colour) for a connection flag and daemon status."""
    if connected:
        return CONNECTED_TEXT, CONNECTED_COLOUR
    if status.running:
        return RUNNING_TEXT, RUNNING_COLOUR
    return STOPPED_TEXT, STOPPED_COLOUR


class DaemonStatusBar(QWidget):
    """Shows a status dot and text, and offers Restart / Re-scan / Daemon… buttons."""

    restart_requested = pyqtSignal()
    rescan_requested = pyqtSignal()
    details_requested = pyqtSignal()

    def __init__(self, service: DaemonService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self.status_dot = QLabel(self)
        self.status_dot.setFixedSize(DOT_SIZE, DOT_SIZE)
        self.status_label = QLabel(STOPPED_TEXT, self)
        self.restart_button = QPushButton(RESTART_TEXT, self)
        self.rescan_button = QPushButton(RESCAN_TEXT, self)
        self.details_button = QPushButton(DETAILS_TEXT, self)
        self._build_layout()
        self._connect_signals()
        self.refresh()

    def _build_layout(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.status_dot)
        layout.addWidget(self.status_label)
        tips = (RESTART_TIP, RESCAN_TIP, DETAILS_TIP)
        buttons = (self.restart_button, self.rescan_button, self.details_button)
        for button, tip in zip(buttons, tips):
            button.setToolTip(tip)
            layout.addWidget(button)
        for first, second in zip(buttons, buttons[1:]):
            QWidget.setTabOrder(first, second)

    def _connect_signals(self) -> None:
        self.restart_button.clicked.connect(self.restart_requested)
        self.rescan_button.clicked.connect(self.rescan_requested)
        self.details_button.clicked.connect(self.details_requested)

    def refresh(self) -> None:
        """Re-read the daemon status and update the dot and text."""
        try:
            status = self._service.status()
        except Exception:  # the service should not raise; be defensive
            logger.exception("Reading daemon status failed")
            status = DaemonStatus(running=False)
        text, colour = describe_status(self._service.connected, status)
        self.status_label.setText(text)
        self.status_dot.setStyleSheet(
            f"background-color: {colour}; border-radius: {DOT_RADIUS}px;")
        self.status_dot.setToolTip(text)
        self.setAccessibleDescription(text)

    def set_busy(self, busy: bool) -> None:
        """Disable Restart and Re-scan while a service action is running."""
        self.restart_button.setEnabled(not busy)
        self.rescan_button.setEnabled(not busy)
