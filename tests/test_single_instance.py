# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the single-instance guard (a unique socket per test)."""

import socket

import pytest

from hueberry import gui_link
from hueberry.single_instance import TOGGLE_SYSMON_MESSAGE, SingleInstance, default_server_name

SIGNAL_TIMEOUT_MS = 2000


@pytest.fixture
def name(tmp_path):
    return str(tmp_path / "instance.sock")


def test_default_name_in_runtime_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert default_server_name() == str(tmp_path / "hueberry" / "gui.sock")


def test_first_instance_listens(qtbot, name):
    first = SingleInstance(name)
    try:
        assert first.notify_or_listen() is False
    finally:
        first.close()


def test_second_instance_notifies_first(qtbot, name):
    first = SingleInstance(name)
    second = SingleInstance(name)
    try:
        assert first.notify_or_listen() is False
        with qtbot.waitSignal(first.show_requested, timeout=2000):
            assert second.notify_or_listen() is True
    finally:
        first.close()


def test_background_launch_probes_without_showing(qtbot, name):
    """A --background second launch detects the first but does not raise its window."""
    first = SingleInstance(name)
    second = SingleInstance(name)
    third = SingleInstance(name)
    shown = []
    first.show_requested.connect(lambda: shown.append(True))
    try:
        assert first.notify_or_listen() is False
        assert second.notify_or_listen(show=False) is True
        with qtbot.waitSignal(first.show_requested, timeout=2000):
            assert third.notify_or_listen() is True  # a later show still works
        assert shown == [True]
    finally:
        first.close()


def test_live_socket_is_not_removed(qtbot, name):
    """Losing the race to another instance: its socket answers, so it is kept and notified."""
    first = SingleInstance(name)
    second = SingleInstance(name)
    third = SingleInstance(name)
    try:
        assert first.notify_or_listen() is False
        with qtbot.waitSignal(first.show_requested, timeout=2000):
            assert second._listen() is None  # as if second's notify ran before first listened
        assert second._server is None
        with qtbot.waitSignal(first.show_requested, timeout=2000):
            assert third.notify_or_listen() is True  # first still owns the socket
    finally:
        first.close()


def test_toggle_sysmon_message_toggles_without_showing(qtbot, name):
    """A --toggle-sysmon second launch toggles the monitor and does not raise the window."""
    first = SingleInstance(name)
    second = SingleInstance(name)
    shown = []
    first.show_requested.connect(lambda: shown.append(True))
    try:
        assert first.notify_or_listen() is False
        with qtbot.waitSignal(first.toggle_sysmon_requested, timeout=SIGNAL_TIMEOUT_MS):
            assert second.notify_or_listen(message=TOGGLE_SYSMON_MESSAGE) is True
        assert shown == []
    finally:
        first.close()


def test_stdlib_client_reaches_live_server(qtbot, name):
    """gui_link's plain AF_UNIX client talks to the QLocalServer (engine -> GUI path)."""
    first = SingleInstance(name)
    shown = []
    first.show_requested.connect(lambda: shown.append(True))
    try:
        assert first.notify_or_listen() is False
        with qtbot.waitSignal(first.toggle_sysmon_requested, timeout=SIGNAL_TIMEOUT_MS):
            assert gui_link.send_message(TOGGLE_SYSMON_MESSAGE, path=first._server.fullServerName())
        assert shown == []
    finally:
        first.close()


def test_stale_socket_is_recovered(qtbot, name):
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale.bind(name)  # the file stays behind, nobody listens: like a crash
    stale.close()
    first = SingleInstance(name)
    second = SingleInstance(name)
    try:
        assert first.notify_or_listen() is False
        with qtbot.waitSignal(first.show_requested, timeout=2000):
            assert second.notify_or_listen() is True
    finally:
        first.close()
