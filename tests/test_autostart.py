# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the XDG autostart entry."""

import pytest

from hueberry import autostart

SCRIPT = "/usr/local/bin/hueberry"
PYTHON = "/usr/bin/python3"


@pytest.fixture
def config_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path


def _entry(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line)


def test_path_under_xdg_config_home(config_home):
    assert autostart.autostart_path() == config_home / "autostart" / "hueberry.desktop"


def test_enable_with_script(config_home):
    autostart.enable(which=lambda _name: SCRIPT, python=PYTHON)
    entry = _entry(autostart.autostart_path())
    assert entry["Type"] == "Application"
    assert entry["Name"] == "Hueberry"
    assert entry["Exec"] == f"{SCRIPT} --background"
    assert entry["Terminal"] == "false"
    assert entry["X-Hueberry-Autostart"] == "true"
    assert autostart.is_enabled()


def test_enable_python_module_fallback(config_home):
    autostart.enable(which=lambda _name: None, python=PYTHON)
    assert _entry(autostart.autostart_path())["Exec"] == f"{PYTHON} -m hueberry --background"


def test_exec_quotes_path_with_spaces():
    line = autostart.exec_line(which=lambda _name: None, python='/opt/my env/bin/py"$%')
    assert line == '"/opt/my env/bin/py\\"\\$%%" -m hueberry --background'


def test_is_enabled_false_without_file(config_home):
    assert not autostart.is_enabled()


def test_disable_removes_our_file(config_home):
    autostart.enable(which=lambda _name: SCRIPT)
    other = autostart.autostart_path().parent / "other.desktop"
    other.write_text("[Desktop Entry]\n", encoding="utf-8")
    autostart.disable()
    assert not autostart.is_enabled()
    assert other.exists()
    autostart.disable()  # already gone: no error


def test_disable_refuses_foreign_file(config_home):
    path = autostart.autostart_path()
    path.parent.mkdir(parents=True)
    path.write_text("[Desktop Entry]\nExec=something\n", encoding="utf-8")
    with pytest.raises(autostart.AutostartError, match="not created by Hueberry"):
        autostart.disable()
    assert path.exists()
    with pytest.raises(autostart.AutostartError):
        autostart.enable(which=lambda _name: SCRIPT)


def test_write_error_reported(config_home):
    (config_home / "autostart").write_text("a file, not a directory", encoding="utf-8")
    with pytest.raises(autostart.AutostartError, match="Cannot write"):
        autostart.enable(which=lambda _name: SCRIPT)


def test_set_autostart_toggles(config_home):
    autostart.set_autostart(True)
    assert autostart.is_enabled()
    autostart.set_autostart(False)
    assert not autostart.is_enabled()
