# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 RazerUI contributors
"""Tests for the main window (offscreen, synchronous worker)."""

import pytest

from razerui.backend.daemon import DaemonService
from razerui.ui import worker
from razerui.ui.main_window import SERIAL_ROLE, MainWindow

MOUSE_SERIAL = "MOUSE0001"
KEYBOARD_SERIAL = "KBD0001"
MOUSE_CAPS = ("dpi", "poll_rate", "lighting", "lighting_static")
KEYBOARD_CAPS = ("lighting", "lighting_static")


def _run_sync(fn, on_done=None, on_error=None):
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


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch, fake_manager_factory, make_device):
    monkeypatch.setattr(worker, "run_async", _run_sync)
    fake_manager_factory.devices = [
        make_device(name="Razer Mouse", device_type="mouse", serial=MOUSE_SERIAL,
                    capabilities=MOUSE_CAPS),
        make_device(name="Razer Keyboard", device_type="keyboard", serial=KEYBOARD_SERIAL,
                    capabilities=KEYBOARD_CAPS),
    ]
    service = DaemonService(pid_path=tmp_path / "missing.pid")
    win = MainWindow(service)
    qtbot.addWidget(win)
    return win, service


def _connect(win):
    win.run_service_action("Connect", win._service.connect)


def test_two_devices_listed(window):
    win, _service = window
    _connect(win)
    assert win.stack.currentWidget() is win.devices_page
    assert win.device_list.count() == 2
    first = win.device_list.item(0)
    assert first.text() == "Razer Mouse (mouse)"
    assert first.toolTip() == MOUSE_SERIAL
    assert first.data(SERIAL_ROLE) == MOUSE_SERIAL
    assert win.device_list.currentRow() == 0


def test_mouse_tab_only_for_mouse(window):
    win, _service = window
    _connect(win)
    win.device_list.setCurrentRow(0)
    assert win.tabs.indexOf(win.mouse_page) >= 0
    win.device_list.setCurrentRow(1)
    assert win.tabs.indexOf(win.mouse_page) < 0
    assert win.info_panel.values["serial"].text() == KEYBOARD_SERIAL
    win.device_list.setCurrentRow(0)
    assert win.tabs.indexOf(win.mouse_page) >= 0


def test_daemon_not_found_shows_empty_state(window, fake_manager_factory):
    win, service = window
    fake_manager_factory.fail = True
    _connect(win)
    assert win.stack.currentWidget() is win.empty_page
    assert service.last_error
    assert win.empty_page.message_label.text() == service.last_error
    assert "Could not connect to daemon" in win.empty_page.message_label.text()
    fake_manager_factory.fail = False
    win.empty_page.retry_button.click()
    assert win.stack.currentWidget() is win.devices_page


def test_repoll_keeps_selection(window, fake_manager_factory):
    win, _service = window
    _connect(win)
    win.device_list.setCurrentRow(1)
    assert win.selected_serial() == KEYBOARD_SERIAL
    fake_manager_factory.devices.reverse()  # the serial now lives on another row
    win.repoll_action.trigger()
    assert fake_manager_factory.constructions == 2
    assert win.selected_serial() == KEYBOARD_SERIAL
    assert win.device_list.currentRow() == 0


class _Capture:
    """run_async stand-in that records calls without running them."""

    def __init__(self):
        self.calls = []

    def __call__(self, fn, on_done=None, on_error=None):
        self.calls.append((fn, on_done, on_error))


def test_daemon_panel_action_blocks_window_actions(window, monkeypatch):
    win, service = window
    capture = _Capture()
    monkeypatch.setattr(worker, "run_async", capture)
    win.daemon_panel.repoll_button.click()
    assert len(capture.calls) == 1
    assert not win.repoll_action.isEnabled()
    assert not win.restart_action.isEnabled()
    win.run_service_action("Repoll", service.repoll)
    win.repoll_action.trigger()
    assert len(capture.calls) == 1
    _fn, on_done, _on_error = capture.calls[0]
    on_done(True)
    assert win.repoll_action.isEnabled()
    assert win.daemon_panel.repoll_button.isEnabled()


def test_window_action_blocks_daemon_panel(window, monkeypatch):
    win, service = window
    capture = _Capture()
    monkeypatch.setattr(worker, "run_async", capture)
    win.repoll_action.trigger()
    assert len(capture.calls) == 1
    panel = win.daemon_panel
    assert not panel.repoll_button.isEnabled()
    assert not panel.restart_button.isEnabled()
    panel._run_action("Restart daemon", service.restart)
    assert len(capture.calls) == 1
    _fn, on_done, _on_error = capture.calls[0]
    on_done(True)
    assert panel.repoll_button.isEnabled()
    assert win.repoll_action.isEnabled()


def test_start_daemon_disabled_when_connected_without_devices(window, fake_manager_factory):
    win, _service = window
    fake_manager_factory.devices = []
    _connect(win)
    assert win.stack.currentWidget() is win.empty_page
    assert not win.empty_page.start_button.isEnabled()
    assert win.empty_page.retry_button.isEnabled()


def test_start_daemon_enabled_when_not_connected(window, fake_manager_factory):
    win, _service = window
    fake_manager_factory.fail = True
    _connect(win)
    assert win.empty_page.start_button.isEnabled()


def test_panel_status_reaches_status_bar(window):
    win, _service = window
    win.lighting_panel.status.emit("hello")
    assert win.statusBar().currentMessage() == "hello"
