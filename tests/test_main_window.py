# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the main window (offscreen, synchronous worker)."""

import pytest
from PyQt6.QtWidgets import QListWidget, QSplitter

from hueberry.backend.daemon import DaemonService
from hueberry.ui import worker
from hueberry.ui.main_window import MainWindow

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
        make_device(name="Test Mouse", device_type="mouse", serial=MOUSE_SERIAL,
                    capabilities=MOUSE_CAPS),
        make_device(name="Test Keyboard", device_type="keyboard", serial=KEYBOARD_SERIAL,
                    capabilities=KEYBOARD_CAPS),
    ]
    service = DaemonService(pid_path=tmp_path / "missing.pid")
    win = MainWindow(service)
    qtbot.addWidget(win)
    return win, service


def _connect(win):
    win.run_service_action("Connect", win._service.connect)


def _card(win, serial):
    return next(card for card in win.home_page.cards() if card.serial == serial)


def _tab_texts(win):
    return [win.tabs.tabText(index) for index in range(win.tabs.count())]


def test_no_list_or_daemon_tab(window):
    win, _service = window
    assert not win.findChildren(QListWidget)
    assert not win.findChildren(QSplitter)
    assert all("Daemo" not in text for text in _tab_texts(win))
    assert not win.daemon_dialog.isModal()


def test_two_device_cards_on_home(window):
    win, _service = window
    _connect(win)
    assert win.stack.currentWidget() is win.home_page
    assert win.home_page.count() == 2
    first = win.home_page.cards()[0]
    assert first.text() == "Test Mouse\nmouse"
    assert first.toolTip() == MOUSE_SERIAL
    assert win.daemon_bar.status_label.text() == "Connected"


def test_open_device_and_back(window):
    win, _service = window
    _connect(win)
    _card(win, KEYBOARD_SERIAL).click()
    assert win.stack.currentWidget() is win.device_page
    assert win.selected_serial() == KEYBOARD_SERIAL
    assert win.device_page.name_label.text() == "Test Keyboard"
    assert win.info_panel.values["serial"].text() == KEYBOARD_SERIAL
    win.device_page.back_button.click()
    assert win.stack.currentWidget() is win.home_page
    assert win.home_page.selected_serial() == KEYBOARD_SERIAL
    assert win.selected_serial() == KEYBOARD_SERIAL


def test_back_button_and_shortcuts(window):
    win, _service = window
    page = win.device_page
    assert page.back_button.text() == "\u2190 Devices"
    sequences = {shortcut.key().toString() for shortcut in page.back_shortcuts}
    assert sequences == {"Alt+Left", "Esc"}


def test_performance_tab_only_for_mouse(window):
    win, _service = window
    _connect(win)
    _card(win, MOUSE_SERIAL).click()
    assert _tab_texts(win) == ["Li&ghting", "Pe&rformance", "&Info"]
    win.device_page.back_button.click()
    _card(win, KEYBOARD_SERIAL).click()
    assert _tab_texts(win) == ["Li&ghting", "&Info"]
    assert win.tabs.indexOf(win.mouse_page) < 0
    win.device_page.back_button.click()
    _card(win, MOUSE_SERIAL).click()
    assert win.tabs.indexOf(win.mouse_page) == 1


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
    assert win.stack.currentWidget() is win.home_page


def test_rescan_keeps_device_page_after_reorder(window, fake_manager_factory):
    win, _service = window
    _connect(win)
    _card(win, KEYBOARD_SERIAL).click()
    fake_manager_factory.devices.reverse()  # the serial now lives at another position
    win.repoll_action.trigger()
    assert fake_manager_factory.constructions == 2
    assert win.stack.currentWidget() is win.device_page
    assert win.selected_serial() == KEYBOARD_SERIAL
    assert win.home_page.cards()[0].serial == KEYBOARD_SERIAL
    assert win.home_page.selected_serial() == KEYBOARD_SERIAL
    assert win.info_panel.values["serial"].text() == KEYBOARD_SERIAL


def test_rescan_on_home_stays_home(window, fake_manager_factory):
    win, _service = window
    _connect(win)
    _card(win, KEYBOARD_SERIAL).click()
    win.device_page.back_button.click()
    fake_manager_factory.devices.reverse()
    win.daemon_bar.rescan_button.click()
    assert fake_manager_factory.constructions == 2
    assert win.stack.currentWidget() is win.home_page
    assert win.home_page.selected_serial() == KEYBOARD_SERIAL


def _shown(win, qtbot):
    win.show()
    qtbot.waitExposed(win)


def test_reload_on_home_keeps_focus(window, qtbot):
    win, _service = window
    _connect(win)
    _shown(win, qtbot)
    win.daemon_bar.rescan_button.setFocus()
    win.reload()
    assert win.stack.currentWidget() is win.home_page
    assert win.focusWidget() is win.daemon_bar.rescan_button


def test_reload_on_device_page_keeps_focus(window, qtbot):
    win, _service = window
    _connect(win)
    _shown(win, qtbot)
    _card(win, KEYBOARD_SERIAL).click()
    focus = win.focusWidget()
    assert focus is win.tabs or win.tabs.isAncestorOf(focus)  # QTabWidget proxies to its bar
    win.daemon_bar.rescan_button.setFocus()
    win.reload()
    assert win.stack.currentWidget() is win.device_page
    assert win.focusWidget() is win.daemon_bar.rescan_button


def test_back_focuses_selected_card(window, qtbot):
    win, _service = window
    _connect(win)
    _shown(win, qtbot)
    _card(win, KEYBOARD_SERIAL).click()
    win.device_page.back_button.click()
    assert win.focusWidget() is _card(win, KEYBOARD_SERIAL)


def test_device_page_leaves_when_device_gone(window, fake_manager_factory):
    win, _service = window
    _connect(win)
    _card(win, KEYBOARD_SERIAL).click()
    fake_manager_factory.devices = fake_manager_factory.devices[:1]
    win.repoll_action.trigger()
    assert win.stack.currentWidget() is win.home_page
    assert win.selected_serial() is None


def test_action_shortcuts_and_labels(window):
    win, _service = window
    assert win.repoll_action.text() == "Re-scan"
    assert win.restart_action.shortcut().toString() == "Ctrl+Shift+R"
    assert win.daemon_bar.restart_button.text() == "Restart"
    assert win.daemon_bar.rescan_button.text() == "Re-scan"
    assert win.daemon_bar.details_button.text() == "Daemon\u2026"


class _Capture:
    """run_async stand-in that records calls without running them."""

    def __init__(self):
        self.calls = []

    def __call__(self, fn, on_done=None, on_error=None):
        self.calls.append((fn, on_done, on_error))


@pytest.mark.parametrize(("button", "method"), [
    ("restart_button", "restart"),
    ("rescan_button", "repoll"),
])
def test_status_bar_buttons_run_service_actions(window, monkeypatch, button, method):
    win, service = window
    capture = _Capture()
    monkeypatch.setattr(worker, "run_async", capture)
    getattr(win.daemon_bar, button).click()
    assert len(capture.calls) == 1
    fn, on_done, _on_error = capture.calls[0]
    assert fn == getattr(service, method)
    assert not win.daemon_bar.restart_button.isEnabled()
    assert not win.daemon_bar.rescan_button.isEnabled()
    assert win.daemon_bar.details_button.isEnabled()
    on_done(True)
    assert win.daemon_bar.restart_button.isEnabled()
    assert win.daemon_bar.rescan_button.isEnabled()


def test_details_button_opens_daemon_dialog(window, qtbot):
    win, _service = window
    win.daemon_bar.details_button.click()
    assert win.daemon_dialog.isVisible()
    assert win.daemon_panel.isVisibleTo(win.daemon_dialog)
    win.daemon_dialog.close()


def test_daemon_panel_action_blocks_window_actions(window, monkeypatch):
    win, service = window
    capture = _Capture()
    monkeypatch.setattr(worker, "run_async", capture)
    win.daemon_panel.repoll_button.click()
    assert len(capture.calls) == 1
    assert not win.repoll_action.isEnabled()
    assert not win.restart_action.isEnabled()
    assert not win.daemon_bar.rescan_button.isEnabled()
    win.run_service_action("Re-scan", service.repoll)
    win.daemon_bar.rescan_button.click()
    assert len(capture.calls) == 1
    _fn, on_done, _on_error = capture.calls[0]
    on_done(True)
    assert win.repoll_action.isEnabled()
    assert win.daemon_bar.rescan_button.isEnabled()
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
    assert win.empty_page.title_label.text() == "<b>No devices found</b>"


def test_start_daemon_enabled_when_not_connected(window, fake_manager_factory):
    win, _service = window
    fake_manager_factory.fail = True
    _connect(win)
    assert win.empty_page.start_button.isEnabled()


def test_panel_status_reaches_status_bar(window):
    win, _service = window
    win.lighting_panel.status.emit("hello")
    assert win.statusBar().currentMessage() == "hello"
