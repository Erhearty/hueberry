# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the tray controller (tray availability injected)."""

import pytest

from hueberry.autostart import AutostartError
from hueberry.settings import Settings
from hueberry.ui.tray import TrayController


class FakeAutostart:
    def __init__(self, enabled=False, error=None):
        self.enabled = enabled
        self.error = error
        self.calls = []

    def is_enabled(self):
        return self.enabled

    def set(self, enabled):
        self.calls.append(enabled)
        if self.error is not None:
            raise self.error
        self.enabled = enabled


@pytest.fixture
def settings(tmp_path):
    return Settings(tmp_path / "settings.json")


def _tray(qtbot, settings, available=False, fake=None):
    fake = fake or FakeAutostart()
    tray = TrayController(settings, available=available, is_autostart_enabled=fake.is_enabled,
                          set_autostart=fake.set)
    return tray, fake


def _texts(tray):
    return [action.text() for action in tray.menu.actions() if not action.isSeparator()]


def test_menu_entries(qtbot, settings):
    tray, _fake = _tray(qtbot, settings)
    assert _texts(tray) == ["Show/Hide Hueberry", "Macros: not started",
                            "Keep running in the background when closed",
                            "Start Hueberry at login", "Quit"]
    assert tray.close_to_tray_action.isChecked()
    assert not tray.autostart_action.isChecked()
    assert tray.tray_icon is None
    assert not tray.close_to_tray  # no tray: closing must quit


def test_available_tray_has_icon(qtbot, settings):
    tray, _fake = _tray(qtbot, settings, available=True)
    assert tray.tray_icon is not None
    assert tray.tray_icon.contextMenu() is tray.menu
    assert tray.close_to_tray
    tray.hide()


def test_toggle_and_quit_signals(qtbot, settings):
    tray, _fake = _tray(qtbot, settings)
    with qtbot.waitSignal(tray.toggle_window_requested, timeout=1000):
        tray.toggle_action.trigger()
    with qtbot.waitSignal(tray.quit_requested, timeout=1000):
        tray.quit_action.trigger()


def test_close_to_tray_persists(qtbot, settings):
    tray, _fake = _tray(qtbot, settings, available=True)
    tray.close_to_tray_action.trigger()
    assert not tray.close_to_tray
    assert Settings(settings.path).close_to_tray is False
    tray.hide()


def test_autostart_checkbox_calls_set_autostart(qtbot, settings):
    tray, fake = _tray(qtbot, settings)
    tray.autostart_action.trigger()
    assert fake.calls == [True]
    assert tray.autostart_action.isChecked()


def test_autostart_failure_reverts(qtbot, settings):
    fake = FakeAutostart(enabled=True, error=AutostartError("read-only"))
    tray, _fake = _tray(qtbot, settings, fake=fake)
    assert tray.autostart_action.isChecked()
    with qtbot.waitSignal(tray.status_message, timeout=1000) as blocker:
        tray.autostart_action.trigger()
    assert fake.calls == [False]
    assert tray.autostart_action.isChecked()
    assert "read-only" in blocker.args[0]


def test_status_text_updates(qtbot, settings):
    tray, _fake = _tray(qtbot, settings, available=True)
    tray.set_status("running")
    assert tray.status_action.text() == "Macros: running"
    assert "running" in tray.tray_icon.toolTip()
    tray.hide()
