# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""App wiring tests: background start, tray, engine lifecycle, single instance."""

import hueberry.app as app
from fake_app import (
    FakeApp,
    FakeEngine,
    FakeInstance,
    FakePool,
    FakeSysmon,
    FakeWindow,
    install,
)
from hueberry.single_instance import TOGGLE_SYSMON_MESSAGE


def test_split_args_strips_background():
    qt_argv, background, toggle_sysmon = app.split_args(["--background", "-style", "fusion"])
    assert background
    assert not toggle_sysmon
    assert qt_argv[1:] == ["-style", "fusion"]
    assert app.split_args([])[1:] == (False, False)


def test_split_args_strips_toggle_sysmon():
    qt_argv, background, toggle_sysmon = app.split_args(["--toggle-sysmon", "-style", "fusion"])
    assert toggle_sysmon
    assert not background
    assert qt_argv[1:] == ["-style", "fusion"]


def test_split_args_toggle_sysmon_with_background():
    qt_argv, background, toggle_sysmon = app.split_args(["--background", "--toggle-sysmon"])
    assert background and toggle_sysmon
    assert qt_argv[1:] == []


def test_background_with_tray_starts_hidden(monkeypatch):
    install(monkeypatch, app, tray_available=True)
    assert app.main(["--background"]) == 0
    (qt_app,) = FakeApp.created
    assert "--background" not in qt_app.argv
    assert qt_app.quit_on_last_window_closed is False
    (window,) = FakeWindow.created
    assert not window.shown
    assert window.engine_started == 1
    assert window.engine is FakeEngine.created[0]


def test_background_without_tray_shows_window(monkeypatch):
    install(monkeypatch, app, tray_available=False)
    assert app.main(["--background"]) == 0
    (qt_app,) = FakeApp.created
    assert qt_app.quit_on_last_window_closed is True
    (window,) = FakeWindow.created
    assert window.shown
    assert window.engine_started == 1


def test_about_to_quit_stops_engine_before_waiting(monkeypatch):
    install(monkeypatch, app)
    order = []
    monkeypatch.setattr(FakeEngine, "stop", lambda self: order.append("stop"))
    monkeypatch.setattr(FakePool, "waitForDone", lambda self, ms: order.append("wait"))
    app.main([])
    assert order == ["stop", "wait"]


def test_quit_requests_reach_the_app(monkeypatch):
    install(monkeypatch, app)
    app.main([])
    (qt_app,) = FakeApp.created
    (window,) = FakeWindow.created
    window.tray.quit_requested.emit()
    window.quit_requested.emit()
    assert qt_app.quit_calls == 2


def test_second_launch_shows_first(monkeypatch):
    install(monkeypatch, app)
    app.main([])
    (window,) = FakeWindow.created
    window.shown = False
    FakeInstance.created[0].show_requested.emit()
    assert window.shown


def test_second_instance_exits_early(monkeypatch):
    themed = install(monkeypatch, app, running=True)
    assert app.main([]) == app.EXIT_OK
    assert FakeWindow.created == []
    assert FakeEngine.created == []
    assert themed == []
    assert FakeInstance.created[0].show is True


def test_second_launch_with_toggle_sysmon_sends_message(monkeypatch):
    themed = install(monkeypatch, app, running=True)
    assert app.main(["--toggle-sysmon"]) == app.EXIT_OK
    (instance,) = FakeInstance.created
    assert instance.message == TOGGLE_SYSMON_MESSAGE
    assert instance.show is False
    assert FakeWindow.created == []
    assert FakeSysmon.created == []
    assert themed == []


def test_first_launch_with_toggle_sysmon_starts_it_hidden(monkeypatch):
    install(monkeypatch, app, tray_available=True)
    assert app.main(["--toggle-sysmon"]) == 0
    (window,) = FakeWindow.created
    assert not window.shown
    (sysmon,) = FakeSysmon.created
    assert sysmon.calls[:2] == ["restore", "start"]


def test_first_launch_toggle_sysmon_keeps_restored_overlay_on(monkeypatch):
    install(monkeypatch, app)
    monkeypatch.setattr(FakeSysmon, "enabled", True)
    monkeypatch.setattr(FakeApp, "exec", lambda self: 0)
    app.main(["--toggle-sysmon"])
    (sysmon,) = FakeSysmon.created
    assert "toggle" not in sysmon.calls
    assert sysmon.is_running()


def test_normal_launch_wires_sysmon(monkeypatch):
    install(monkeypatch, app)
    assert app.main([]) == 0
    (window,) = FakeWindow.created
    (sysmon,) = FakeSysmon.created
    assert window.shown
    assert window.sysmon is sysmon
    assert sysmon.calls == ["restore", "shutdown"]
    FakeInstance.created[0].toggle_sysmon_requested.emit()
    assert sysmon.calls[-1] == "toggle"


def test_about_to_quit_shuts_sysmon_down(monkeypatch):
    install(monkeypatch, app)
    monkeypatch.setattr(FakeApp, "exec", lambda self: 0)
    app.main([])
    (qt_app,) = FakeApp.created
    (sysmon,) = FakeSysmon.created
    assert sysmon.calls == ["restore"]
    qt_app.aboutToQuit.emit()
    assert sysmon.calls[-1] == "shutdown"


def test_background_second_instance_does_not_raise_first(monkeypatch):
    install(monkeypatch, app, running=True)
    assert app.main(["--background"]) == app.EXIT_OK
    assert FakeInstance.created[0].show is False
    assert FakeWindow.created == []
