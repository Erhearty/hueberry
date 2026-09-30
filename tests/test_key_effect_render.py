# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Deterministic tests for per-key effect rendering."""

import random

from hueberry.backend.key_effect_render import BLACK, press_lifetime, render_group
from hueberry.backend.key_effects import (
    EFFECT_BREATHING, EFFECT_REACTIVE, EFFECT_RIPPLE, EFFECT_SPECTRUM, EFFECT_STARLIGHT,
    EFFECT_WAVE, KeyEffect,
)

RED = (255, 0, 0)
BLUE = (0, 0, 255)
GRID = [(row, col) for row in range(3) for col in range(5)]
SEED = 7


def _render(effect, t=0.0, presses=(), leds=GRID, seed=SEED):
    return render_group(effect, leds, t, list(presses), random.Random(seed))


def test_static_and_brightness():
    frame = _render(KeyEffect(palette=(RED,), brightness=0.5))
    assert set(frame) == set(GRID)
    assert set(frame.values()) == {(127, 0, 0)}


def test_empty_group_renders_nothing():
    assert _render(KeyEffect(), leds=[]) == {}


def test_wave_angle_zero_varies_along_columns():
    frame = _render(KeyEffect(effect=EFFECT_WAVE, palette=(RED, BLUE), angle=0.0, width=1.0))
    for col in range(5):
        assert len({frame[(row, col)] for row in range(3)}) == 1
    assert frame[(0, 0)] != frame[(0, 2)]


def test_wave_angle_ninety_varies_along_rows():
    frame = _render(KeyEffect(effect=EFFECT_WAVE, palette=(RED, BLUE), angle=90.0, width=1.0))
    for row in range(3):
        assert len({frame[(row, col)] for col in range(5)}) == 1
    assert frame[(0, 0)] != frame[(1, 0)]


def test_wave_moves_over_time():
    effect = KeyEffect(effect=EFFECT_WAVE, palette=(RED, BLUE), speed=1.0)
    assert _render(effect, t=0.0) != _render(effect, t=0.25)


def test_breathing_dark_then_bright():
    effect = KeyEffect(effect=EFFECT_BREATHING, palette=(RED,), speed=1.0)
    assert set(_render(effect, t=0.0).values()) == {BLACK}
    assert set(_render(effect, t=0.5).values()) == {RED}


def test_spectrum_changes_hue():
    effect = KeyEffect(effect=EFFECT_SPECTRUM, speed=1.0)
    assert set(_render(effect, t=0.0).values()) == {RED}
    assert set(_render(effect, t=1 / 3).values()) != {RED}


def test_reactive_fades():
    effect = KeyEffect(effect=EFFECT_REACTIVE, palette=(RED,), fade=1.0)
    presses = [(0.0, (1, 2))]
    fresh = _render(effect, t=0.0, presses=presses)
    half = _render(effect, t=0.5, presses=presses)
    gone = _render(effect, t=1.5, presses=presses)
    assert fresh[(1, 2)] == RED and fresh[(0, 0)] == BLACK
    assert half[(1, 2)] == (127, 0, 0)
    assert gone[(1, 2)] == BLACK
    assert press_lifetime(effect) == 1.0


def test_reactive_none_lights_whole_group():
    effect = KeyEffect(effect=EFFECT_REACTIVE, palette=(RED,))
    assert set(_render(effect, presses=[(0.0, None)]).values()) == {RED}


def test_ripple_ring_grows():
    effect = KeyEffect(effect=EFFECT_RIPPLE, palette=(RED,), speed=0.25, width=0.25,
                       fade=5.0)
    presses = [(0.0, (0, 0))]
    frame = _render(effect, t=1.0, presses=presses)  # radius 2 keys, thickness 1 key
    assert frame[(0, 2)][0] > 200
    assert frame[(0, 0)] == BLACK
    assert frame[(0, 4)] == BLACK


def test_ripple_none_starts_at_centroid():
    effect = KeyEffect(effect=EFFECT_RIPPLE, palette=(RED,), speed=1.0, width=0.25)
    frame = _render(effect, t=0.0, presses=[(0.0, None)])
    assert frame[(1, 2)] == RED
    assert frame[(0, 0)] == BLACK


def test_starlight_is_seeded():
    effect = KeyEffect(effect=EFFECT_STARLIGHT, palette=(RED, BLUE), density=0.5)
    first, again = _render(effect, seed=SEED), _render(effect, seed=SEED)
    assert first == again
    assert BLACK in first.values()
    assert any(colour != BLACK for colour in first.values())
    assert set(_render(effect.with_changes(density=0.0)).values()) == {BLACK}
