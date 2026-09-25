# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the engine entry point: parent watcher, argument handling, exit codes."""

import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from hueberry.macro_engine import main as main_mod
from hueberry.macro_engine.server import AlreadyRunning

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def sock_dir():
    path = Path(tempfile.mkdtemp(prefix="hbm", dir="/tmp"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


def test_parent_watcher_uses_getppid_and_pidfd():
    """alive() compares getppid; pidfd failures fall back to polling."""
    def _fail(pid):
        raise ProcessLookupError(3, "No such process")

    watcher = main_mod.ParentWatcher(42, getppid=lambda: 42, pidfd_open=_fail)
    assert watcher.alive() and watcher.fileno() is None
    assert not main_mod.ParentWatcher(42, getppid=lambda: 1, pidfd_open=None).alive()
    read_fd, write_fd = os.pipe()
    os.close(write_fd)
    watcher = main_mod.ParentWatcher(42, getppid=lambda: 42, pidfd_open=lambda pid: read_fd)
    assert watcher.fileno() == read_fd
    watcher.close()
    assert watcher.fileno() is None


class _FakeServer:
    created = []

    def __init__(self, path, parent_watcher=None):
        self.path = path
        self.watcher = parent_watcher
        self.error = None
        _FakeServer.created.append(self)

    def request_stop(self, reason="x"):
        pass

    def serve(self):
        if self.error is not None:
            raise self.error


@pytest.fixture
def fake_main(monkeypatch):
    monkeypatch.setattr(main_mod, "set_parent_death_signal", lambda: True)
    monkeypatch.setattr(main_mod, "EngineServer", _FakeServer)
    monkeypatch.setattr(_FakeServer, "created", [])
    return _FakeServer


def test_main_requires_parent_pid():
    """--parent-pid is mandatory."""
    with pytest.raises(SystemExit) as info:
        main_mod.main([])
    assert info.value.code != 0


def test_main_serves_and_restores_handlers(fake_main, sock_dir):
    """With a live parent main() serves and restores signal handlers."""
    before = signal.getsignal(signal.SIGTERM)
    assert main_mod.main(["--parent-pid", str(os.getppid()), "--socket", str(sock_dir / "s")]) == 0
    (server,) = fake_main.created
    assert server.path == sock_dir / "s"
    assert signal.getsignal(signal.SIGTERM) is before


def test_main_parent_already_gone(fake_main):
    """A parent that is not our parent means exit without serving."""
    assert main_mod.main(["--parent-pid", "999999999"]) == main_mod.EXIT_OK
    assert fake_main.created == []


def test_main_already_running_exit_code(fake_main, monkeypatch):
    """AlreadyRunning maps to EXIT_ALREADY_RUNNING."""
    monkeypatch.setattr(_FakeServer, "serve", lambda self: (_ for _ in ()).throw(AlreadyRunning("x")))
    assert main_mod.main(["--parent-pid", str(os.getppid())]) == main_mod.EXIT_ALREADY_RUNNING


def test_main_without_evdev(monkeypatch):
    """Missing evdev is a clear non-zero exit."""
    monkeypatch.setitem(sys.modules, "evdev", None)
    assert main_mod.main(["--parent-pid", "1"]) == main_mod.EXIT_NO_EVDEV


def test_engine_runs_without_evdev_or_qt():
    """In a clean interpreter without evdev the engine imports without Qt and exits clearly."""
    code = ("import sys; sys.modules['evdev'] = None\n"
            "from hueberry.macro_engine.main import main\n"
            "assert not any(m.startswith('PyQt6') for m in sys.modules), 'Qt imported'\n"
            "sys.exit(main(['--parent-pid', '1']))\n")
    result = subprocess.run([sys.executable, "-c", code], cwd=PROJECT_ROOT, capture_output=True,
                            text=True, timeout=30, check=False)
    assert result.returncode == main_mod.EXIT_NO_EVDEV, result.stderr
    assert "python-evdev is not installed" in result.stderr
