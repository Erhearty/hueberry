# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Scaffold sanity tests: package metadata, entry point, fake openrazer, headers."""

from pathlib import Path

import pytest

from fake_app import FakePool, FakeWindow, install

SPDX_LICENSE = "# SPDX-License-Identifier: GPL-3.0-or-later"
SPDX_COPYRIGHT = "# SPDX-FileCopyrightText: 2025 Hueberry contributors"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHECKED_DIRS = (PROJECT_ROOT / "hueberry", PROJECT_ROOT / "tests")


def test_package_has_version():
    """The package exposes a version string."""
    import hueberry

    assert hueberry.__version__ == "0.1.0"


def test_main_returns_zero(monkeypatch):
    """main() builds the app and window, starts a connect and returns exec()'s code."""
    import hueberry.app as app

    themed = install(monkeypatch, app)
    assert app.main([]) == 0
    assert len(themed) == 1 and themed[0].name == app.APP_NAME
    (window,) = FakeWindow.created
    assert window.shown
    assert [label for label, _fn in window.actions] == ["Connect"]
    assert FakePool.waits == [app.SHUTDOWN_WAIT_MS]


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
