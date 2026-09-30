# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the per-zone record of applied hardware effects."""

import json
import stat

from hueberry.backend import device_effects_store as store
from hueberry.backend.lighting import (
    PARAM_COLOUR1, PARAM_COLOUR2, PARAM_DIRECTION, PARAM_TIME, REACTIVE_MED, WAVE_LEFT,
)

SERIAL = "KBD0001"
ZONE = "main"
OTHER_ZONE = "logo"
RED = (255, 0, 0)
FILE_MODE = 0o600


def test_config_path_under_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert store.config_path() == tmp_path / "hueberry" / "device_effects.json"


def test_missing_file_is_none():
    assert store.load_record(SERIAL, ZONE) is None


def test_round_trip_keeps_only_effect_params():
    params = {PARAM_COLOUR1: RED, PARAM_COLOUR2: (0, 0, 1), PARAM_TIME: REACTIVE_MED,
              PARAM_DIRECTION: WAVE_LEFT}
    store.save_record(SERIAL, ZONE, "reactive", params)
    store.save_record(SERIAL, OTHER_ZONE, "wave", params)
    assert store.load_record(SERIAL, ZONE) == (
        "reactive", {PARAM_COLOUR1: [255, 0, 0], PARAM_TIME: REACTIVE_MED})
    assert store.load_record(SERIAL, OTHER_ZONE) == ("wave", {PARAM_DIRECTION: WAVE_LEFT})
    assert store.load_record("OTHER", ZONE) is None
    mode = stat.S_IMODE(store.config_path().stat().st_mode)
    assert mode == FILE_MODE
    data = json.loads(store.config_path().read_text())
    assert data["version"] == 1
    assert data["devices"][SERIAL][ZONE]["effect"] == "reactive"


def test_save_rejects_invalid():
    for key, params in (("nope", {}), ("static", {}), ("static", {PARAM_COLOUR1: (300, 0, 0)}),
                        ("reactive", {PARAM_COLOUR1: RED, PARAM_TIME: True})):
        try:
            store.save_record(SERIAL, ZONE, key, params)
        except ValueError:
            continue
        raise AssertionError(f"{key} {params} was accepted")
    assert not store.config_path().exists()


def _write(data):
    path = store.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def test_invalid_entry_is_none():
    _write({"version": 1, "devices": {SERIAL: {
        ZONE: {"effect": "static", "params": {PARAM_COLOUR1: [1, 2]}},
        OTHER_ZONE: {"effect": "bogus", "params": {}},
        "x": "not an object",
        "y": {"effect": "none"},
    }}})
    assert store.load_record(SERIAL, ZONE) is None
    assert store.load_record(SERIAL, OTHER_ZONE) is None
    assert store.load_record(SERIAL, "x") is None
    assert store.load_record(SERIAL, "y") == ("none", {})


def test_corrupt_file_is_ignored_and_save_recovers(caplog):
    path = store.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json")
    assert store.load_record(SERIAL, ZONE) is None
    assert "device effects" in caplog.text
    store.save_record(SERIAL, ZONE, "static", {PARAM_COLOUR1: RED})
    assert store.load_record(SERIAL, ZONE) == ("static", {PARAM_COLOUR1: [255, 0, 0]})


def test_wrong_version_is_ignored():
    _write({"version": 2, "devices": {SERIAL: {ZONE: {"effect": "none", "params": {}}}}})
    assert store.load_record(SERIAL, ZONE) is None
