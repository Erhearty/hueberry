# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the per-key effect model (hueberry.backend.key_effects)."""

import pytest

from hueberry.backend.effects import PresetError
from hueberry.backend.key_effects import (
    EFFECT_LABELS, EFFECT_REACTIVE, EFFECT_RIPPLE, EFFECT_STATIC, EFFECT_TYPES, EFFECT_WAVE,
    KeyEffect, is_animated, uses_presses,
)

WAVE = KeyEffect(effect=EFFECT_WAVE, palette=((255, 0, 0), (0, 0, 255)), speed=2.5,
                 brightness=0.5, direction="reverse", angle=90.0, width=0.25,
                 density=0.3, fade=2.0)


def test_round_trip():
    data = WAVE.to_dict()
    assert data["palette"] == ["#ff0000", "#0000ff"]
    assert KeyEffect.from_dict(data) == WAVE


def test_missing_optional_fields_take_defaults():
    effect = KeyEffect.from_dict({"effect": EFFECT_STATIC, "palette": ["#010203"]})
    assert effect == KeyEffect(palette=((1, 2, 3),))


@pytest.mark.parametrize("changes", [
    {"effect": "nope"}, {"palette": ()}, {"palette": ((0, 0, 0),) * 17},
    {"palette": ((256, 0, 0),)}, {"speed": -1}, {"speed": 11}, {"brightness": 1.5},
    {"angle": 361}, {"width": 0.0}, {"density": 2}, {"fade": 0}, {"direction": "up"},
    {"speed": True},
])
def test_validation_rejects(changes):
    with pytest.raises(PresetError):
        WAVE.with_changes(**changes).validate()


@pytest.mark.parametrize("data", [
    [], {"palette": ["#000000"]}, {"effect": EFFECT_STATIC, "palette": "#000000"},
    {"effect": EFFECT_STATIC, "palette": ["red"]},
])
def test_from_dict_rejects(data):
    with pytest.raises(PresetError):
        KeyEffect.from_dict(data)


def test_labels_and_helpers():
    assert set(EFFECT_TYPES) == {"static", "wave", "breathing", "spectrum", "reactive",
                                 "ripple", "starlight"}
    assert all(EFFECT_LABELS[effect] for effect in EFFECT_TYPES)
    assert uses_presses(EFFECT_REACTIVE) and uses_presses(EFFECT_RIPPLE)
    assert not uses_presses(EFFECT_WAVE)
    assert not is_animated(EFFECT_STATIC) and is_animated(EFFECT_WAVE)
