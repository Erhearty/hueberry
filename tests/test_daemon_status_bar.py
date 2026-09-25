# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the daemon status bar (fake openrazer from conftest, no real daemon)."""

import pytest

from hueberry.backend.daemon import DaemonService
from hueberry.ui import daemon_status_bar
from hueberry.ui.daemon_status_bar import DaemonStatusBar

FAKE_PID = "4242"


@pytest.fixture
def service(tmp_path):
    return DaemonService(pid_path=tmp_path / "missing.pid")


@pytest.fixture
def bar(qtbot, service):
    widget = DaemonStatusBar(service)
    qtbot.addWidget(widget)
    return widget


def test_labels(bar):
    assert bar.restart_button.text() == "Restart"
    assert bar.rescan_button.text() == "Re-scan"
    assert bar.details_button.text() == "Daemon\u2026"


def test_not_running(bar):
    assert bar.status_label.text() == "Daemon not running"
    assert daemon_status_bar.STOPPED_COLOUR in bar.status_dot.styleSheet()


def test_connected_after_refresh(bar, service):
    assert service.connect()
    bar.refresh()
    assert bar.status_label.text() == "Connected"
    assert daemon_status_bar.CONNECTED_COLOUR in bar.status_dot.styleSheet()


def test_running_but_not_connected(qtbot, tmp_path):
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text(FAKE_PID, encoding="ascii")
    service = DaemonService(pid_path=pid_path, is_alive=lambda _pid: True)
    widget = DaemonStatusBar(service)
    qtbot.addWidget(widget)
    assert widget.status_label.text() == "Daemon running"


@pytest.mark.parametrize(("button", "signal"), [
    ("restart_button", "restart_requested"),
    ("rescan_button", "rescan_requested"),
    ("details_button", "details_requested"),
])
def test_buttons_emit(bar, qtbot, button, signal):
    with qtbot.waitSignal(getattr(bar, signal)):
        getattr(bar, button).click()


def test_set_busy(bar):
    bar.set_busy(True)
    assert not bar.restart_button.isEnabled()
    assert not bar.rescan_button.isEnabled()
    assert bar.details_button.isEnabled()
    bar.set_busy(False)
    assert bar.restart_button.isEnabled()
    assert bar.rescan_button.isEnabled()
