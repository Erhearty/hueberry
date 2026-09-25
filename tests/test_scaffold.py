# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Scaffold sanity tests: package metadata, entry point, fake openrazer, headers."""

from pathlib import Path

import pytest

SPDX_LICENSE = "# SPDX-License-Identifier: GPL-3.0-or-later"
SPDX_COPYRIGHT = "# SPDX-FileCopyrightText: 2025 Hueberry contributors"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHECKED_DIRS = (PROJECT_ROOT / "hueberry", PROJECT_ROOT / "tests")


def test_package_has_version():
    """The package exposes a version string."""
    import hueberry

    assert hueberry.__version__ == "0.1.0"


class _FakeApp:
    """Stands in for QApplication so main() does not start an event loop."""

    def __init__(self, argv):
        self.argv = argv
        self.name = None

    def setApplicationName(self, name):
        self.name = name

    def exec(self):
        return 0


class _FakeWindow:
    """Stands in for MainWindow; records show() and service actions."""

    created: list = []

    def __init__(self, service):
        self.service = service
        self.shown = False
        self.actions = []
        _FakeWindow.created.append(self)

    def show(self):
        self.shown = True

    def run_service_action(self, label, fn):
        self.actions.append((label, fn))


class _FakePool:
    """Stands in for QThreadPool; records waitForDone timeouts."""

    waits: list = []

    @classmethod
    def globalInstance(cls):
        return cls()

    def waitForDone(self, msecs):
        _FakePool.waits.append(msecs)
        return True


def test_main_returns_zero(monkeypatch):
    """main() builds the app and window, starts a connect and returns exec()'s code."""
    import hueberry.app as app

    monkeypatch.setattr(app, "QApplication", _FakeApp)
    monkeypatch.setattr(app, "MainWindow", _FakeWindow)
    monkeypatch.setattr(app, "QThreadPool", _FakePool)
    monkeypatch.setattr(_FakeWindow, "created", [])
    monkeypatch.setattr(_FakePool, "waits", [])
    assert app.main([]) == 0
    (window,) = _FakeWindow.created
    assert window.shown
    assert [label for label, _fn in window.actions] == ["Connect"]
    assert _FakePool.waits == [app.SHUTDOWN_WAIT_MS]


def test_openrazer_client_is_fake(fake_client, fake_manager_factory):
    """Importing openrazer.client inside tests yields the fake module."""
    import openrazer.client

    assert openrazer.client is fake_client
    assert openrazer.client.DaemonNotFound is fake_client.DaemonNotFound
    fake_manager_factory.fail = True
    with pytest.raises(fake_client.DaemonNotFound):
        openrazer.client.DeviceManager()


def _python_files():
    for directory in CHECKED_DIRS:
        yield from sorted(directory.rglob("*.py"))


def test_every_python_file_has_spdx_header():
    """Every .py file starts with the SPDX header (after an optional shebang)."""
    files = list(_python_files())
    assert files
    for path in files:
        lines = path.read_text(encoding="utf-8").splitlines()
        if lines and lines[0].startswith("#!"):
            lines = lines[1:]
        assert lines[:2] == [SPDX_LICENSE, SPDX_COPYRIGHT], path
