# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""App wiring tests: background start, tray, engine lifecycle, single instance."""

import hueberry.app as app
from fake_app import FakeApp, FakeEngine, FakeInstance, FakePool, FakeWindow, install


def test_split_args_strips_background():
    qt_argv, background = app.split_args(["--background", "-style", "fusion"])
    assert background
    assert qt_argv[1:] == ["-style", "fusion"]
    assert app.split_args([])[1] is False


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
