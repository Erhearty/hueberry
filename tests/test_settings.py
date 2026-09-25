# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the persistent GUI settings."""

import json

import pytest

from hueberry.settings import Settings, settings_path


@pytest.fixture
def config_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path


def test_defaults_without_file(config_home):
    settings = Settings()
    assert settings.path == config_home / "hueberry" / "settings.json"
    assert settings.close_to_tray is True


def test_round_trip(config_home):
    Settings().set("close_to_tray", False)
    assert Settings().close_to_tray is False


@pytest.mark.parametrize("content", ["{not json", "[1, 2]", '{"close_to_tray": "no"}'])
def test_corrupt_file_falls_back(config_home, content):
    path = settings_path()
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")
    assert Settings().close_to_tray is True


def test_unknown_keys_preserved(config_home):
    path = settings_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"future_option": [1, 2]}), encoding="utf-8")
    Settings().set("close_to_tray", False)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"future_option": [1, 2], "close_to_tray": False}
