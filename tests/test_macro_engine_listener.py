# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the engine's listening socket: stale-socket probe and directory modes."""

import errno
import os
import shutil
import socket
import stat
import tempfile
from pathlib import Path

import pytest

from hueberry.macro_engine import listener
from hueberry.macros import protocol

PUBLIC_DIR_MODE = 0o755


@pytest.fixture
def sock_dir():
    path = Path(tempfile.mkdtemp(prefix="hbl", dir="/tmp"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


class _SilentSocket:
    """A connected socket whose peer never replies."""

    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _refusing(code):
    def connect(path, timeout):
        raise OSError(code, os.strerror(code))
    return connect


def test_probe_connect_without_reply_counts_as_running(sock_dir):
    """A connect that succeeds is 'running' even if nobody answers; the socket is closed."""
    silent = _SilentSocket()
    assert listener.probe_engine(sock_dir / "s", connect=lambda path, timeout: silent)
    assert silent.closed


@pytest.mark.parametrize("code, running", [
    (errno.ENOENT, False), (errno.ECONNREFUSED, False), (errno.EACCES, True), (errno.EAGAIN, True),
])
def test_probe_only_enoent_and_refused_are_stale(sock_dir, code, running):
    """Only ENOENT/ECONNREFUSED mean a stale socket; other errors are treated as running."""
    assert listener.probe_engine(sock_dir / "s", connect=_refusing(code)) is running


def test_probe_timeout_counts_as_running(sock_dir):
    """A connect timeout (errno None) is not proof of a dead engine."""
    def connect(path, timeout):
        raise socket.timeout("timed out")
    assert listener.probe_engine(sock_dir / "s", connect=connect)


def test_probe_against_real_listener_does_not_wait_for_reply(sock_dir):
    """A real listening socket that never accepts still probes as running."""
    path = sock_dir / "s"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(path))
        server.listen(1)
        assert listener.probe_engine(path)
    finally:
        server.close()


def test_prepare_socket_refuses_when_probe_says_running(sock_dir):
    """An injected probe reporting a live engine raises and leaves the socket file alone."""
    path = sock_dir / "s"
    path.touch()
    with pytest.raises(listener.AlreadyRunning):
        listener.prepare_socket(path, probe=lambda p: True)
    assert path.exists()


def test_existing_parent_is_not_chmodded(sock_dir):
    """An arbitrary existing directory keeps its mode."""
    os.chmod(sock_dir, PUBLIC_DIR_MODE)
    listener.prepare_socket(sock_dir / "s", probe=lambda p: False).close()
    assert stat.S_IMODE(os.stat(sock_dir).st_mode) == PUBLIC_DIR_MODE
    assert stat.S_IMODE(os.stat(sock_dir / "s").st_mode) == listener.SOCKET_MODE


def test_created_directory_is_private(sock_dir):
    """A directory we create is 0700."""
    target = sock_dir / "new" / "s"
    listener.prepare_socket(target, probe=lambda p: False).close()
    assert stat.S_IMODE(os.stat(target.parent).st_mode) == listener.SOCKET_DIR_MODE


def test_default_directory_is_tightened(sock_dir, monkeypatch):
    """The default hueberry/ dir under the runtime dir is forced to 0700 even if it existed."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(sock_dir))
    path = protocol.socket_path()
    path.parent.mkdir(mode=PUBLIC_DIR_MODE)
    os.chmod(path.parent, PUBLIC_DIR_MODE)
    listener.prepare_socket(path, probe=lambda p: False).close()
    assert stat.S_IMODE(os.stat(path.parent).st_mode) == listener.SOCKET_DIR_MODE
