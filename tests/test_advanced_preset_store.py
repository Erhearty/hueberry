# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for advanced_presets.json load/save."""

import json
import stat

import pytest

from hueberry.backend import advanced_preset_store as store
from hueberry.backend.advanced_presets import AdvancedPreset, DeviceProgram, KeyGroup
from hueberry.backend.effects import PresetError

FILE_MODE = 0o600
PRESET = AdvancedPreset("neon", "Neon", (DeviceProgram("KBD1", (KeyGroup("All", ((0, 1),)),)),))


def test_missing_file_is_empty():
    assert store.load() == ([], None)


def test_round_trip():
    store.save([PRESET])
    path = store.config_path()
    assert path.name == "advanced_presets.json"
    assert stat.S_IMODE(path.stat().st_mode) == FILE_MODE
    assert json.loads(path.read_text())["version"] == 1
    assert store.load() == ([PRESET], None)
    assert store.find_preset("neon", [PRESET]) is PRESET
    assert store.find_preset("x", [PRESET]) is None


@pytest.mark.parametrize("content", [b"{ nope", b'{"version": 2, "presets": []}',
                                     b'{"version": 1, "presets": [{"key": "a"}]}'])
def test_corrupt_file_quarantined(content):
    path = store.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    presets, error = store.load()
    assert presets == [] and ".bak" in error
    assert not path.exists()
    assert path.with_name(path.name + ".bak").read_bytes() == content


def test_save_rejects_duplicates_and_invalid():
    with pytest.raises(PresetError):
        store.save([PRESET, PRESET])
    with pytest.raises(PresetError):
        store.save([PRESET.with_changes(label="")])
    assert not store.config_path().exists()


def test_unique_key():
    assert store.unique_key("My Effect!", []) == "my-effect"
    assert store.unique_key("My Effect", ["my-effect"]) == "my-effect-2"
    assert store.unique_key("My Effect", ["my-effect", "my-effect-2"]) == "my-effect-3"
    assert store.unique_key("???", []) == "effect"
    assert len(store.unique_key("a" * 80, ["a" * 64])) <= 64
