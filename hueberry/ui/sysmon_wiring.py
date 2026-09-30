# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Wire a ``SysmonController`` into the main window and the tray.

Kept out of :mod:`hueberry.ui.main_window` so that file stays small. The
window asks :func:`add_page` for the page (None without a controller), then
:func:`connect_window` for the nav button, the shortcut and the signal
wiring. :func:`connect_tray` syncs the tray's System monitor check item with
the controller and can be called on its own.
"""

from typing import Any, Callable

from PyQt6.QtCore import QObject, Qt
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QStackedWidget, QWidget

from hueberry.ui import sysmon_sections
from hueberry.ui.sysmon_page import SysmonPage

__all__ = ["SysmonNav", "add_page", "connect_tray", "connect_window"]

SYSMON_TEXT = "Sysmon"
SYSMON_SHORTCUT = "Ctrl+Shift+Y"
SYSMON_TIP = "Show, hide and configure the system monitor overlay (Ctrl+Shift+Y)"
START_FAILED_TEXT = "Could not show the system monitor: {error}"
UNKNOWN_ERROR_TEXT = "unknown error"

StatusSink = Callable[[str], None]


class SysmonNav(QObject):
    """The Sysmon nav button and action; opens the page and returns to the previous one."""

    def __init__(self, window: Any, page: SysmonPage) -> None:
        super().__init__(window)
        self._window = window
        self.page = page
        self._before: QWidget | None = None  # page to return to from Sysmon
        self.button = window.header.add_nav(SYSMON_TEXT, SYSMON_TIP)
        self.action = QAction(SYSMON_TEXT, window)
        self.action.setShortcut(QKeySequence(SYSMON_SHORTCUT))
        self.action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        window.addAction(self.action)
        self.action.triggered.connect(self.show_page)
        self.button.clicked.connect(self.show_page)
        page.back_requested.connect(self.leave_page)

    def show_page(self) -> None:
        """Open the Sysmon page, remembering the page to return to."""
        stack = self._window.stack
        current = stack.currentWidget()
        if current is not self.page:
            self._before = current
        self.page.refresh()
        stack.setCurrentWidget(self.page)
        self.page.toggle_button.setFocus()

    def leave_page(self) -> None:
        """Return to the page shown before Sysmon, then reload (it may be stale)."""
        window = self._window
        previous = self._before or window.home_page
        self._before = None
        window.stack.setCurrentWidget(previous)
        window.reload()
        if window.stack.currentWidget() is window.home_page:
            window.home_page.focus_selected()


def add_page(stack: QStackedWidget, controller: Any) -> SysmonPage | None:
    """Create the Sysmon page and add it to ``stack``; None without a controller.

    The detectors are looked up on :mod:`sysmon_sections` at call time so tests
    can monkeypatch them.
    """
    if controller is None:
        return None
    page = SysmonPage(controller, stack, disk_detector=sysmon_sections.detect_disks,
                      gpu_detector=sysmon_sections.detect_gpu_cards)
    stack.addWidget(page)
    return page


def connect_window(window: Any, controller: Any, tray: Any = None) -> SysmonNav | None:
    """Add the nav button/shortcut for ``window.sysmon_page`` and wire its signals.

    Returns None (and does nothing) when the window has no Sysmon page.
    """
    page = window.sysmon_page
    if page is None:
        return None
    nav = SysmonNav(window, page)
    page.status.connect(window.show_status)
    page.bind_key_requested.connect(window.show_macros)
    if tray is not None:
        connect_tray(tray, controller, window.show_status)
    return nav


def connect_tray(tray: Any, controller: Any, show_status: StatusSink | None = None) -> None:
    """Sync the tray's System monitor item with ``controller`` both ways.

    Checking the item starts the overlay, unchecking stops it; a failed start
    unchecks the item again and reports via ``show_status``. The controller's
    ``state_changed`` updates the item without re-emitting ``sysmon_toggled``.
    """
    def on_toggled(checked: bool) -> None:
        if not checked:
            controller.stop()
        elif not controller.start():
            tray.set_sysmon_checked(controller.is_running())
            if show_status is not None:
                error = controller.last_error or UNKNOWN_ERROR_TEXT
                show_status(START_FAILED_TEXT.format(error=error))

    tray.sysmon_toggled.connect(on_toggled)
    controller.state_changed.connect(tray.set_sysmon_checked)
    tray.set_sysmon_checked(controller.is_running())
