# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the main window (offscreen, synchronous worker)."""

import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QListWidget, QSplitter

import hueberry.app as app_module
from hueberry.backend import advanced_runtime
from hueberry.backend.daemon import DaemonService
from hueberry.settings import Settings
from hueberry.sysmon.config import SysmonConfig
from hueberry.ui import effects_wiring, sysmon_sections, sysmon_wiring, worker
from hueberry.ui.main_window import MainWindow
from hueberry.ui.tray import TrayController

MOUSE_SERIAL = "MOUSE0001"
KEYBOARD_SERIAL = "KBD0001"
MOUSE_CAPS = ("dpi", "poll_rate", "lighting", "lighting_static")
KEYBOARD_CAPS = ("lighting", "lighting_static")
SYSMON_START_ERROR = "waybar not found"


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


class FakeTray(QObject):
    """Stands in for TrayController: signals plus a settable close_to_tray."""

    toggle_window_requested = pyqtSignal()
    status_message = pyqtSignal(str)

    def __init__(self, close_to_tray):
        super().__init__()
        self.close_to_tray = close_to_tray
        self.statuses = []

    def set_status(self, text):
        self.statuses.append(text)


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch, fake_manager_factory, make_device):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
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
    lists = [lst for lst in win.findChildren(QListWidget)
             if not any(page.isAncestorOf(lst) for page in (
                 win.macros_page, win.effects_page))]
    assert not lists
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
    assert win.empty_page.title_label.text() == "No devices found"


def test_start_daemon_enabled_when_not_connected(window, fake_manager_factory):
    win, _service = window
    fake_manager_factory.fail = True
    _connect(win)
    assert win.empty_page.start_button.isEnabled()


class _RecordingRuntime:
    """Stands in for the shared advanced runtime; counts shutdown calls."""

    def __init__(self):
        self.shutdowns = 0

    def shutdown(self):
        self.shutdowns += 1


class _Signal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)


def test_app_stops_animations_on_quit(monkeypatch):
    fake_app = type("FakeApp", (), {})()
    fake_app.aboutToQuit = _Signal()
    runtime = _RecordingRuntime()
    monkeypatch.setattr(advanced_runtime, "shared_runtime", lambda: runtime)
    app_module._stop_animations_on_quit(fake_app)
    for slot in fake_app.aboutToQuit.slots:
        slot()
    assert runtime.shutdowns == 1


def test_effects_page_opens_and_returns(window):
    win, _service = window
    _connect(win)
    win.effects_nav.action.trigger()
    assert win.stack.currentWidget() is win.effects_page
    assert win.effects_nav.action.shortcut().toString() == "Ctrl+E"
    assert win.effects_page.device_list.count() == 0  # neither test device has a key matrix
    win.effects_page.back_button.click()
    assert win.stack.currentWidget() is win.home_page
    win.effects_nav.button.click()
    assert win.stack.currentWidget() is win.effects_page


def test_create_effect_nav_text_and_shortcut(window):
    win, _service = window
    nav = win.effects_nav
    assert nav.button.text() == "Create effect\u2026"
    assert nav.action.text() == "Create effect\u2026"
    assert nav.action.shortcut().toString() == "Ctrl+E"
    assert "Ctrl+E" in nav.button.toolTip()


def test_reload_restores_last_effect(window, monkeypatch):
    win, _service = window
    calls = []
    monkeypatch.setattr(effects_wiring, "restore_last", lambda devices: calls.append(devices))
    _connect(win)
    assert calls and len(calls[-1]) == 2


def test_reload_survives_restore_error(window, monkeypatch):
    win, _service = window

    def broken(_devices):
        raise RuntimeError("restore broke")

    monkeypatch.setattr(effects_wiring, "restore_last", broken)
    win.reload()
    assert win.statusBar().currentMessage() == "Animation error: restore broke"


def test_panel_status_reaches_status_bar(window):
    win, _service = window
    win.lighting_panel.status.emit("hello")
    assert win.statusBar().currentMessage() == "hello"


def _tray_window(qtbot, service, close_to_tray):
    tray = FakeTray(close_to_tray)
    win = MainWindow(service, tray=tray)
    qtbot.addWidget(win)
    return win, tray


def test_macros_page_opens_and_returns_home(window):
    win, _service = window
    _connect(win)
    win.macros_action.trigger()
    assert win.stack.currentWidget() is win.macros_page
    win.macros_page.back_button.click()
    assert win.stack.currentWidget() is win.home_page


def test_macros_button_opens_macros_page(window):
    win, _service = window
    win.macros_button.click()
    assert win.stack.currentWidget() is win.macros_page
    assert win.macros_action.shortcut().toString() == "Ctrl+M"


def test_macros_status_reaches_status_bar(window):
    win, _service = window
    win.macros_page.status.emit("macros saved")
    assert win.statusBar().currentMessage() == "macros saved"


def test_tray_status_forwarding(window, qtbot):
    _win, service = window
    win, tray = _tray_window(qtbot, service, close_to_tray=True)
    win.macros_page.engine_summary.emit("running")
    assert tray.statuses[-1] == "running"
    tray.status_message.emit("tray says hi")
    assert win.statusBar().currentMessage() == "tray says hi"


def test_close_hides_to_tray(window, qtbot):
    _win, service = window
    win, _tray = _tray_window(qtbot, service, close_to_tray=True)
    win.show()
    with qtbot.assertNotEmitted(win.quit_requested):
        event = QCloseEvent()
        win.closeEvent(event)
    assert not event.isAccepted()
    assert not win.isVisible()


def test_close_quits_when_close_to_tray_off(window, qtbot):
    _win, service = window
    win, _tray = _tray_window(qtbot, service, close_to_tray=False)
    with qtbot.waitSignal(win.quit_requested, timeout=0):
        event = QCloseEvent()
        win.closeEvent(event)
    assert event.isAccepted()


def test_close_without_tray_accepts(window):
    win, _service = window
    event = QCloseEvent()
    win.closeEvent(event)
    assert event.isAccepted()


def test_tray_toggle_shows_and_hides(window, qtbot):
    _win, service = window
    win, tray = _tray_window(qtbot, service, close_to_tray=True)
    tray.toggle_window_requested.emit()
    assert win.isVisible()
    tray.toggle_window_requested.emit()
    assert not win.isVisible()


class FakeSysmon(QObject):
    """Stands in for SysmonController; records start/stop and emits ``state_changed``."""

    state_changed = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.config = SysmonConfig()
        self.running = False
        self.start_ok = True
        self.last_error = None
        self.calls = []

    def is_running(self):
        return self.running

    def start(self):
        self.calls.append("start")
        if not self.start_ok:
            self.last_error = SYSMON_START_ERROR
            return False
        self.running = True
        self.state_changed.emit(True)
        return True

    def stop(self):
        self.calls.append("stop")
        self.running = False
        self.state_changed.emit(False)

    def apply(self, cfg):
        self.config = cfg
        return []


def _real_tray():
    """A TrayController without a system tray and with a no-op autostart."""
    return TrayController(Settings(), available=False, is_autostart_enabled=lambda: False,
                          set_autostart=lambda _enabled: None)


@pytest.fixture
def sysmon_window(window, qtbot, monkeypatch):
    monkeypatch.setattr(sysmon_sections, "detect_disks", tuple)
    monkeypatch.setattr(sysmon_sections, "detect_gpu_cards", list)
    _win, service = window
    controller = FakeSysmon()
    tray = _real_tray()
    win = MainWindow(service, tray=tray, sysmon=controller)
    qtbot.addWidget(win)
    return win, controller, tray


def test_no_sysmon_page_without_controller(window):
    win, _service = window
    assert win.sysmon_page is None
    assert win.sysmon_nav is None
    win.show_sysmon()
    assert all(action.shortcut().toString() != sysmon_wiring.SYSMON_SHORTCUT
               for action in win.actions())


def test_sysmon_page_opens_and_returns_to_previous_page(sysmon_window):
    win, _controller, _tray = sysmon_window
    _connect(win)
    _card(win, KEYBOARD_SERIAL).click()
    nav = win.sysmon_nav
    assert nav.action.shortcut().toString() == "Ctrl+Shift+Y"
    nav.action.trigger()
    assert win.stack.currentWidget() is win.sysmon_page
    win.sysmon_page.back_button.click()
    assert win.stack.currentWidget() is win.device_page
    win.device_page.back_button.click()
    nav.button.click()
    assert win.stack.currentWidget() is win.sysmon_page
    win.sysmon_page.back_requested.emit()
    assert win.stack.currentWidget() is win.home_page


def test_reload_stays_on_sysmon_page(sysmon_window):
    win, _controller, _tray = sysmon_window
    _connect(win)
    win.show_sysmon()
    win.reload()
    assert win.stack.currentWidget() is win.sysmon_page


def test_sysmon_bind_key_opens_macros_and_status_reaches_bar(sysmon_window):
    win, _controller, _tray = sysmon_window
    win.show_sysmon()
    win.sysmon_page.bind_key_requested.emit()
    assert win.stack.currentWidget() is win.macros_page
    win.sysmon_page.status.emit("sysmon applied")
    assert win.statusBar().currentMessage() == "sysmon applied"


def test_tray_sysmon_toggle_starts_and_stops(sysmon_window):
    _win, controller, tray = sysmon_window
    assert not tray.sysmon_action.isChecked()
    tray.sysmon_action.setChecked(True)
    assert controller.calls == ["start"]
    assert controller.running
    tray.sysmon_action.setChecked(False)
    assert controller.calls == ["start", "stop"]
    assert not controller.running


def test_controller_state_updates_tray_without_reemitting(sysmon_window, qtbot):
    _win, controller, tray = sysmon_window
    with qtbot.assertNotEmitted(tray.sysmon_toggled):
        controller.state_changed.emit(True)
    assert tray.sysmon_action.isChecked()
    assert controller.calls == []


def test_tray_failed_start_unchecks_and_reports(sysmon_window):
    win, controller, tray = sysmon_window
    controller.start_ok = False
    tray.sysmon_action.setChecked(True)
    assert not tray.sysmon_action.isChecked()
    assert SYSMON_START_ERROR in win.statusBar().currentMessage()


def test_connect_tray_initialises_from_controller(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    controller = FakeSysmon()
    controller.running = True
    tray = _real_tray()
    with qtbot.assertNotEmitted(tray.sysmon_toggled):
        sysmon_wiring.connect_tray(tray, controller)
    assert tray.sysmon_action.isChecked()
    assert controller.calls == []
