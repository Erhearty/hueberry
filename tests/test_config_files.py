# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the shared atomic JSON config helpers."""

import stat

import pytest

from hueberry import config_files

KIND = "test file"


def test_config_dir_uses_xdg_config_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config_files.config_dir() == tmp_path / "hueberry"
    monkeypatch.delenv("XDG_CONFIG_HOME")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert config_files.config_dir() == tmp_path / "home" / ".config" / "hueberry"


def test_atomic_write_replaces_with_mode_0600(tmp_path):
    path = tmp_path / "sub" / "data.json"
    config_files.atomic_write(path, b"one")
    config_files.atomic_write(path, b"two")
    assert path.read_bytes() == b"two"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert [p.name for p in path.parent.iterdir()] == ["data.json"]


def test_atomic_write_failure_keeps_old_file_and_no_temp(monkeypatch, tmp_path):
    path = tmp_path / "data.json"
    config_files.atomic_write(path, b"old")

    def _boom(fd):
        raise OSError("disk full")

    monkeypatch.setattr(config_files.os, "fsync", _boom)
    with pytest.raises(OSError, match="disk full"):
        config_files.atomic_write(path, b"new")
    assert path.read_bytes() == b"old"
    assert [p.name for p in tmp_path.iterdir()] == ["data.json"]


def test_quarantine_moves_to_bak(tmp_path):
    path = tmp_path / "data.json"
    path.write_bytes(b"{bad")
    message = config_files.quarantine(path, ValueError("broken"), KIND)
    assert "data.json.bak" in message and "broken" in message
    assert not path.exists()
    assert (tmp_path / "data.json.bak").read_bytes() == b"{bad"


def test_quarantine_reports_move_failure(tmp_path):
    message = config_files.quarantine(tmp_path / "absent.json", ValueError("broken"), KIND)
    assert "could not be moved aside" in message


def test_load_file_missing_corrupt_and_valid(tmp_path):
    path = tmp_path / "data.json"
    assert config_files.load_file(path, KIND, config_files.parse_json, dict) == ({}, None)
    path.write_bytes(config_files.dump_json({"a": 1}))
    assert config_files.load_file(path, KIND, config_files.parse_json, dict) == ({"a": 1}, None)
    path.write_bytes(b"\xff\xfe")
    value, error = config_files.load_file(path, KIND, config_files.parse_json, dict)
    assert value == {} and error and "data.json.bak" in error


def test_parse_json_rejects_oversize():
    with pytest.raises(ValueError):
        config_files.parse_json(b"{}", max_bytes=1)
