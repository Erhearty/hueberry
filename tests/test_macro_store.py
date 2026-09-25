# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the macros.json store."""

import json
import stat
from pathlib import Path

import pytest

from hueberry.macros import store
from hueberry.macros.model import DelayStep, DeviceMacros, KeyStep, Macro, MacroConfig, ModelError


def _config():
    macro = Macro("m1", "Copy", True, "BTN_SIDE", [KeyStep("KEY_LEFTCTRL", "press"), KeyStep("KEY_C"),
                                                   DelayStep(10), KeyStep("KEY_LEFTCTRL", "release")])
    return MacroConfig([DeviceMacros("1532:0084:Mouse:usb-1", "Mouse", [macro])])


def test_config_path_uses_xdg_config_home(monkeypatch, tmp_path):
    """$XDG_CONFIG_HOME wins; otherwise ~/.config."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert store.config_path() == tmp_path / "hueberry" / "macros.json"
    monkeypatch.delenv("XDG_CONFIG_HOME")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert store.config_path() == tmp_path / "home" / ".config" / "hueberry" / "macros.json"


def test_missing_file_is_empty_config(tmp_path):
    """No file yet: empty config and no error."""
    assert store.load(tmp_path / "macros.json") == (MacroConfig(), None)


def test_round_trip_with_mode_and_version(monkeypatch, tmp_path):
    """save -> load returns the same config; file is 0600 and versioned."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    store.save(_config())
    path = tmp_path / "hueberry" / "macros.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text())["version"] == 1
    assert store.load() == (_config(), None)
    assert [p.name for p in path.parent.iterdir()] == ["macros.json"]


@pytest.mark.parametrize("content", [
    b"{not json",
    b"\xff\xfe",
    b"[]",
    b'{"version": 2, "devices": []}',
    b'{"version": 1, "devices": [{"identity": "x", "name": "", "macros": [{"id": "a", "name": "a", '
    b'"enabled": true, "trigger": "BTN_SIDE", "steps": [{"type": "shell", "command": "id"}]}]}]}',
])
def test_corrupt_file_moves_to_bak(tmp_path, content):
    """Unparseable or invalid files are moved to macros.json.bak with an error."""
    path = tmp_path / "macros.json"
    path.write_bytes(content)
    config, error = store.load(path)
    assert config == MacroConfig()
    assert error and "macros.json.bak" in error
    assert not path.exists()
    assert (tmp_path / "macros.json.bak").read_bytes() == content


def test_save_refuses_invalid_config(tmp_path):
    """Invalid configs are never written."""
    config = _config()
    config.devices[0].macros[0].steps.append(DelayStep(-5))
    with pytest.raises(ModelError):
        store.save(config, tmp_path / "macros.json")
    assert not (tmp_path / "macros.json").exists()


def test_save_is_atomic_on_failure(monkeypatch, tmp_path):
    """A failure mid-save leaves the old file intact and no temp file behind."""
    path = tmp_path / "macros.json"
    store.save(MacroConfig(), path)
    before = path.read_bytes()

    def _boom(fd):
        raise OSError("disk full")

    monkeypatch.setattr(store.os, "fsync", _boom)
    with pytest.raises(OSError, match="disk full"):
        store.save(_config(), path)
    assert path.read_bytes() == before
    assert sorted(p.name for p in Path(tmp_path).iterdir()) == ["macros.json"]
