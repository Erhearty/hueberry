# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Daemon status and lifecycle controls backed by a DaemonService.

Actions run through ``worker.run_async(...)`` looked up on the
:mod:`hueberry.ui.worker` module, so tests can monkeypatch it.
"""

import logging
from functools import partial
from typing import Any, Callable

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QFormLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from hueberry.backend.daemon import DaemonService, DaemonStatus
from hueberry.ui import worker

logger = logging.getLogger(__name__)

UNKNOWN_TEXT = "\u2014"
RUNNING_TEXT = "Running"
STOPPED_TEXT = "Not running"
CONNECTED_SUFFIX = " (connected)"
STOP_CONFIRM_TITLE = "Stop OpenRazer daemon"
STOP_CONFIRM_TEXT = "Stop the OpenRazer daemon? Devices will not respond until it is started again."


class DaemonPanel(QWidget):
    """Shows daemon state and offers repoll/restart/stop/start and daemon settings.

    ``daemon_changed`` is emitted after every action completes (successfully or
    not); ``status`` carries human-readable results. ``busy_changed(bool)``
    reports this panel's own action starting/finishing, and
    :meth:`set_external_busy` lets the owner block the panel while a window
    action runs, so only one service action is in flight at a time.
    """

    status = pyqtSignal(str)
    daemon_changed = pyqtSignal()
    busy_changed = pyqtSignal(bool)

    def __init__(self, service: DaemonService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._busy = False
        self._external_busy = False
        self._build_widgets()
        self._build_layout()
        self._connect_signals()
        chain = self._tab_chain()
        for first, second in zip(chain, chain[1:]):
            QWidget.setTabOrder(first, second)
        self.refresh()

    def _build_widgets(self) -> None:
        self.running_value = QLabel(UNKNOWN_TEXT, self)
        self.daemon_version_value = QLabel(UNKNOWN_TEXT, self)
        self.client_version_value = QLabel(UNKNOWN_TEXT, self)
        self.repoll_button = QPushButton("&Repoll devices", self)
        self.restart_button = QPushButton("Re&start daemon", self)
        self.stop_button = QPushButton("S&top daemon", self)
        self.start_button = QPushButton("St&art daemon", self)
        self.sync_check = QCheckBox("S&ync effects across devices", self)
        self.screensaver_check = QCheckBox("Turn &off devices on screensaver", self)

    def _build_layout(self) -> None:
        form = QFormLayout()
        form.addRow("Daemon:", self.running_value)
        form.addRow("Daemon version:", self.daemon_version_value)
        form.addRow("Client version:", self.client_version_value)
        buttons = QHBoxLayout()
        for button in (self.repoll_button, self.restart_button, self.stop_button,
                       self.start_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        outer = QVBoxLayout(self)
        outer.addLayout(form)
        outer.addLayout(buttons)
        outer.addWidget(self.sync_check)
        outer.addWidget(self.screensaver_check)
        outer.addStretch(1)

    def _connect_signals(self) -> None:
        service = self._service
        self.repoll_button.clicked.connect(
            lambda: self._run_action("Repoll devices", service.repoll))
        self.restart_button.clicked.connect(
            lambda: self._run_action("Restart daemon", service.restart))
        self.stop_button.clicked.connect(self._on_stop_clicked)
        self.start_button.clicked.connect(
            lambda: self._run_action("Start daemon", service.start))
        self.sync_check.clicked.connect(
            lambda checked: self._run_action(
                "Sync effects", partial(service.set_sync_effects, checked)))
        self.screensaver_check.clicked.connect(
            lambda checked: self._run_action(
                "Screensaver setting", partial(service.set_screensaver_off, checked)))

    def _tab_chain(self) -> list[QWidget]:
        return [self.repoll_button, self.restart_button, self.stop_button, self.start_button,
                self.sync_check, self.screensaver_check]

    # -- state ---------------------------------------------------------------

    def refresh(self) -> None:
        """Re-read the daemon status and update labels, checkboxes and buttons."""
        try:
            status = self._service.status()
        except Exception as exc:  # the service should not raise; be defensive
            logger.exception("Reading daemon status failed")
            self.status.emit(f"Daemon error: {exc}")
            status = DaemonStatus(running=False)
        self._show_status(status)
        self._update_enabled(status)

    def _show_status(self, status: DaemonStatus) -> None:
        running = RUNNING_TEXT if status.running else STOPPED_TEXT
        if self._service.connected:
            running += CONNECTED_SUFFIX
        self.running_value.setText(running)
        self.daemon_version_value.setText(status.daemon_version or UNKNOWN_TEXT)
        self.client_version_value.setText(status.client_version or UNKNOWN_TEXT)
        self._show_setting(self.sync_check, status.sync_effects)
        self._show_setting(self.screensaver_check, status.turn_off_on_screensaver)

    @staticmethod
    def _show_setting(check: QCheckBox, value: bool | None) -> None:
        check.blockSignals(True)
        check.setChecked(bool(value))
        check.blockSignals(False)

    @property
    def busy(self) -> bool:
        """True while one of this panel's own actions is running."""
        return self._busy

    def set_external_busy(self, busy: bool) -> None:
        """Disable the controls while another component runs a service action."""
        self._external_busy = busy
        self.refresh()

    def _update_enabled(self, status: DaemonStatus) -> None:
        idle = not self._busy and not self._external_busy
        connected = self._service.connected
        self.repoll_button.setEnabled(idle)
        self.restart_button.setEnabled(idle)
        self.stop_button.setEnabled(idle and connected)
        self.start_button.setEnabled(idle and not status.running)
        self.sync_check.setEnabled(idle and status.sync_effects is not None)
        self.screensaver_check.setEnabled(idle and status.turn_off_on_screensaver is not None)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.refresh()
        self.busy_changed.emit(busy)

    # -- actions -------------------------------------------------------------

    def confirm_stop(self) -> bool:
        """Ask the user to confirm stopping the daemon. Overridable in tests."""
        answer = QMessageBox.question(
            self, STOP_CONFIRM_TITLE, STOP_CONFIRM_TEXT,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _on_stop_clicked(self) -> None:
        try:
            confirmed = self.confirm_stop()
        except Exception:  # never let an exception escape a slot
            logger.exception("Stop confirmation failed")
            confirmed = False
        if not confirmed:
            self.status.emit("Stop daemon cancelled")
            return
        self._run_action("Stop daemon", self._service.stop)

    def _run_action(self, label: str, fn: Callable[[], Any]) -> None:
        if self._busy or self._external_busy:
            self.status.emit(f"{label}: another action is still running")
            return
        self.status.emit(f"{label}\u2026")
        self._set_busy(True)
        try:
            worker.run_async(fn, partial(self._on_action_done, label),
                             partial(self._on_action_failed, label))
        except Exception as exc:  # never let an exception escape a slot
            logger.exception("Could not start daemon action %s", label)
            self._on_action_failed(label, str(exc))

    def _on_action_done(self, label: str, ok: Any) -> None:
        if ok:
            self.status.emit(f"{label}: done")
        else:
            reason = self._service.last_error or "unknown error"
            self.status.emit(f"{label} failed: {reason}")
        self._finish()

    def _on_action_failed(self, label: str, message: str) -> None:
        logger.warning("%s failed: %s", label, message)
        self.status.emit(f"{label} failed: {message}")
        self._finish()

    def _finish(self) -> None:
        self._set_busy(False)
        self.daemon_changed.emit()
