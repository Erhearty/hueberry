# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the presets.json store."""

import json
import stat

import pytest

from hueberry.backend import effects, preset_store, presets
from hueberry.backend.effects import Preset, PresetError

RED = (255, 0, 0)


def _preset(key="calm", label="Calm"):
    return Preset(key=key, label=label, effect=effects.EFFECT_BREATHE, palette=(RED,), speed=0.5)


@pytest.fixture
def config_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path / "hueberry"


def test_missing_file_is_no_presets(config_home):
    assert preset_store.config_path() == config_home / "presets.json"
    assert preset_store.load() == ([], None)


def test_round_trip_with_mode_and_version(config_home):
    user = [_preset(), _preset("glow", "Glow")]
    preset_store.save(user)
    path = config_home / "presets.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text())["version"] == 1
    assert preset_store.load() == (user, None)
    assert [p.name for p in config_home.iterdir()] == ["presets.json"]


@pytest.mark.parametrize("content", [
    b"{nope", b"[]", b'{"version": 2, "presets": []}', b'{"version": 1, "presets": {}}',
    b'{"version": 1, "presets": [{"key": "x"}]}',
])
def test_corrupt_file_moves_to_bak(config_home, content):
    config_home.mkdir(parents=True)
    path = config_home / "presets.json"
    path.write_bytes(content)
    loaded, error = preset_store.load()
    assert loaded == []
    assert error and "presets.json.bak" in error
    assert not path.exists()
    assert (config_home / "presets.json.bak").read_bytes() == content


def test_builtin_clash_and_duplicates_are_skipped(config_home):
    config_home.mkdir(parents=True)
    clash = _preset(presets.PRESET_KEY, "Mine").to_dict()
    data = {"version": 1, "presets": [clash, _preset().to_dict(), _preset(label="Again").to_dict()]}
    (config_home / "presets.json").write_text(json.dumps(data))
    assert preset_store.load() == ([_preset()], None)


@pytest.mark.parametrize("user", [
    [presets.ERHEART], [_preset(presets.PRESET_KEY)], [_preset(), _preset()],
    [_preset(label="")],
])
def test_save_refuses_builtins_duplicates_and_invalid(config_home, user):
    with pytest.raises(PresetError):
        preset_store.save(user)
    assert not (config_home / "presets.json").exists()


def test_all_and_find():
    everything = preset_store.all_presets([_preset()])
    assert everything[0] is presets.ERHEART
    assert preset_store.find_preset("calm", everything) == _preset()
    assert preset_store.find_preset("missing", everything) is None


def test_unique_key():
    assert preset_store.unique_key("My Cool Preset!", []) == "my-cool-preset"
    assert preset_store.unique_key("Calm", ["calm"]) == "calm-2"
    assert preset_store.unique_key("Calm", ["calm", "calm-2"]) == "calm-3"
    assert preset_store.unique_key("Erheart", []) == "erheart-2"
    assert preset_store.unique_key("???", []) == "preset"
    long_key = preset_store.unique_key("x" * 80, ["x" * 64])
    assert len(long_key) == 64 and long_key.endswith("-2")
    _preset(long_key).validate()
