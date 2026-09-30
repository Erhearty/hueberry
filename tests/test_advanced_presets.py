# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the advanced (per-key) preset model."""

import pytest

from hueberry.backend.advanced_presets import AdvancedPreset, DeviceProgram, KeyGroup
from hueberry.backend.effects import PresetError
from hueberry.backend.key_effects import EFFECT_WAVE, KeyEffect

WASD = KeyGroup("WASD", ((2, 3), (3, 2), (3, 3), (3, 4)), KeyEffect(palette=((255, 0, 0),)))
REST = KeyGroup("Rest", ((0, 1),), KeyEffect(effect=EFFECT_WAVE, angle=45.0))
PRESET = AdvancedPreset("gaming", "Gaming", (DeviceProgram("KBD1", (WASD, REST), "Keyboard"),))


def test_round_trip():
    data = PRESET.to_dict()
    assert data["programs"][0]["groups"][0]["leds"] == [[2, 3], [3, 2], [3, 3], [3, 4]]
    assert AdvancedPreset.from_dict(data) == PRESET
    assert PRESET.program_for("KBD1").name == "Keyboard"
    assert PRESET.program_for("nope") is None


def test_overlapping_groups_rejected():
    clash = REST.with_changes(leds=((3, 3),))
    preset = PRESET.with_changes(programs=(DeviceProgram("KBD1", (WASD, clash)),))
    with pytest.raises(PresetError, match="two groups"):
        preset.validate()


def test_same_keys_on_different_devices_allowed():
    AdvancedPreset("two", "Two", (DeviceProgram("A", (WASD,)),
                                  DeviceProgram("B", (WASD,)))).validate()


@pytest.mark.parametrize("preset", [
    PRESET.with_changes(key="Bad Key"),
    PRESET.with_changes(label="  "),
    PRESET.with_changes(label="x" * 65),
    PRESET.with_changes(programs=(DeviceProgram("A"), DeviceProgram("A"))),
    PRESET.with_changes(programs=(DeviceProgram("A", (WASD.with_changes(leds=((-1, 0),)),)),)),
    PRESET.with_changes(programs=(DeviceProgram("A", (WASD.with_changes(name=""),)),)),
    PRESET.with_changes(programs=(DeviceProgram(""),)),
])
def test_validation_rejects(preset):
    with pytest.raises(PresetError):
        preset.validate()


@pytest.mark.parametrize("data", [
    [], {"key": "a", "label": "A"},
    {"key": "a", "label": "A", "programs": [{"serial": "S", "groups": [
        {"name": "G", "leds": [[0]], "effect": {"effect": "static", "palette": ["#000000"]}}]}]},
    {"key": "a", "label": "A", "programs": [{"serial": "S", "groups": [
        {"name": "G", "leds": [], "effect": None}]}]},
])
def test_from_dict_rejects(data):
    with pytest.raises(PresetError):
        AdvancedPreset.from_dict(data)
