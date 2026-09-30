# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the Qt-free GUI link (app actions over the instance socket)."""

import shutil
import socket
import tempfile
from pathlib import Path

import pytest

from hueberry import gui_link

ACCEPT_TIMEOUT_S = 2.0
READ_SIZE = 64


@pytest.fixture
def short_dir():
    """A short temp dir (AF_UNIX paths are limited to ~108 bytes)."""
    path = tempfile.mkdtemp(prefix="hb")
    yield Path(path)
    shutil.rmtree(path, ignore_errors=True)


def test_send_action_delivers_the_action_line(short_dir, monkeypatch):
    """A listening socket receives exactly b'toggle-sysmon\\n'."""
    path = str(short_dir / "gui.sock")
    monkeypatch.setattr(gui_link, "default_server_name", lambda: path)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(path)
        server.listen(1)
        server.settimeout(ACCEPT_TIMEOUT_S)
        assert gui_link.send_action(gui_link.APP_ACTION_TOGGLE_SYSMON) is True
        connection, _ = server.accept()
        with connection:
            connection.settimeout(ACCEPT_TIMEOUT_S)
            assert connection.recv(READ_SIZE) == b"toggle-sysmon\n"


def test_missing_socket_returns_false(short_dir, caplog):
    """No listener: False and a warning, never an exception."""
    with caplog.at_level("WARNING", logger="hueberry.gui_link"):
        assert gui_link.send_message(b"toggle-sysmon\n", path=str(short_dir / "none.sock")) is False
    assert caplog.records and "toggle-sysmon" not in caplog.text


def test_unknown_action_is_refused():
    """Only allow-listed actions can be encoded or sent."""
    with pytest.raises(ValueError):
        gui_link.action_message("rm -rf")
    with pytest.raises(ValueError):
        gui_link.send_action("shell")


def test_every_action_has_a_label():
    """The editor can label every allow-listed action."""
    assert set(gui_link.APP_ACTION_LABELS) == set(gui_link.APP_ACTIONS)
    assert gui_link.action_message(gui_link.APP_ACTION_TOGGLE_SYSMON) == b"toggle-sysmon\n"
