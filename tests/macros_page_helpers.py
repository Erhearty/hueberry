# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Shared helpers of the Macros page tests: a fake engine, a synchronous worker, page drivers."""

from PyQt6.QtCore import Qt

from hueberry.backend import macro_engine as states
from hueberry.macros.protocol import EngineUnavailable
from hueberry.ui.macros_page import MacrosPage

MOUSE = "1532:0084:Test Mouse:usb-1"
KEYBOARD = "1532:0203:Test Keyboard:usb-2"
OLD_PAD = "1532:0999:Old Pad:usb-3"
ALL_OK = {"uinput_ok": True, "unreadable_inputs": []}


def run_sync(fn, on_done=None, on_error=None):
    """Synchronous stand-in for worker.run_async."""
    try:
        result = fn()
    except Exception as exc:
        if on_error is not None:
            on_error(str(exc))
        return None
    if on_done is not None:
        on_done(result)
    return None


class FakeEngine:
    """MacroEngineService stand-in."""

    def __init__(self, state=states.STATE_RUNNING, permissions=None, error=None):
        self.state = state
        self.last_error = error
        self.permissions = permissions if permissions is not None else dict(ALL_OK)
        self.states = {MOUSE: "active", KEYBOARD: None}
        self.config_error = None
        self.fail = False
        self.calls = []
        self.extra_devices = []  # more list_devices rows, appended as given

    def poll(self):
        return self.state

    def list_devices(self):
        self.calls.append("list_devices")
        if self.fail:
            raise EngineUnavailable("gone")
        devices = [{"identity": MOUSE, "name": "Test Mouse", "has_keys": True, "state": self.states[MOUSE],
                    "vendor": "1532", "kind": "mouse"},
                   {"identity": KEYBOARD, "name": "Test Keyboard", "has_keys": True,
                    "state": self.states[KEYBOARD], "vendor": "1532", "kind": "keyboard"},
                   {"identity": "x", "name": "Lid switch", "has_keys": False, "state": None}]
        devices += self.extra_devices
        return {"devices": devices, "permissions": self.permissions}

    def status(self):
        self.calls.append("status")
        devices = [{"identity": MOUSE, "name": "Test Mouse", "state": self.states[MOUSE], "error": None}]
        return {"devices": devices, "recording": None, "config_error": self.config_error}

    def reload(self):
        self.calls.append("reload")
        return self.status()

    def spawn(self):
        self.calls.append("spawn")
        self.state = states.STATE_STARTING
        return True

    def wait_ready(self):
        self.calls.append("wait_ready")
        self.state = states.STATE_RUNNING
        return True


def make_page(qtbot, engine):
    """A refreshed MacrosPage over ``engine``."""
    page = MacrosPage(engine)
    qtbot.addWidget(page)
    page.refresh()
    return page


def device_texts(page):
    """The texts of the page's device items."""
    return [page.device_list.item(row).text() for row in range(page.device_list.count())]


def select(page, identity):
    """Make the device ``identity`` the current device."""
    for row in range(page.device_list.count()):
        if page.device_list.item(row).data(Qt.ItemDataRole.UserRole) == identity:
            page.device_list.setCurrentRow(row)
            return
    raise AssertionError(identity)


def add_macro(page, trigger="BTN_SIDE"):
    """Add a one-step macro 'Copy' through the editor."""
    page.add_button.click()
    editor = page.editor
    editor.name_edit.setText("Copy")
    editor.trigger_combo.setCurrentText(trigger)
    editor.add_key_button.click()
    editor.step_dialog.accept()
    editor.accept()


def row_widget(view, index=0):
    """The row widget shown over item ``index`` of ``view``."""
    return view.itemWidget(view.item(index))
