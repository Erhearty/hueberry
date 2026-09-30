# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Pure maths turning a :class:`KeyEffect` into colours of one key group.

:func:`render_group` is stateless: the time, the recent key presses and a
random source are passed in, so every effect renders deterministically in
tests. Key positions are ``(row, col)`` matrix cells; distances are measured
in keys. Nothing here imports openrazer or Qt.
"""

import colorsys
import math
import random
from typing import Iterable, Sequence

from hueberry.backend.effects import CHANNEL_MAX, DIRECTION_REVERSE, RGB
from hueberry.backend.key_effects import (
    EFFECT_BREATHING, EFFECT_REACTIVE, EFFECT_RIPPLE, EFFECT_SPECTRUM, EFFECT_STARLIGHT,
    EFFECT_WAVE, KeyEffect,
)

__all__ = ["BLACK", "Cell", "Press", "press_lifetime", "render_group"]

Cell = tuple[int, int]
#: A key press: when it happened (seconds) and where (None: anywhere in the group).
Press = tuple[float, Cell | None]

BLACK: RGB = (0, 0, 0)
FULL = 1.0
NONE = 0.0
HALF = 0.5
FULL_TURN_DEGREES = 360.0
FULL_TURN = 2 * math.pi
RIPPLE_KEYS_PER_CYCLE = 8.0  # ring radius growth (keys per second) at speed 1
RIPPLE_MAX_THICKNESS = 4.0  # ring thickness in keys at width 1
SATURATION = 1.0
DIRECTION_DIGITS = 9  # rounding of the wave direction: cos(90 degrees) is exactly 0
VALUE = 1.0


def press_lifetime(effect: KeyEffect) -> float:
    """Seconds a press stays visible: older presses can be forgotten."""
    return effect.fade


def _scaled(colour: RGB, level: float) -> RGB:
    red, green, blue = colour
    return (int(red * level), int(green * level), int(blue * level))


def _blend(palette: Sequence[RGB], pos: float) -> RGB:
    """Colour at cycle position ``pos``, blended between neighbouring palette colours."""
    count = len(palette)
    scaled = (pos % 1) * count
    index = int(scaled) % count
    frac = scaled - int(scaled)
    first, second = palette[index], palette[(index + 1) % count]
    return tuple(int(a + (b - a) * frac) for a, b in zip(first, second))  # type: ignore[return-value]


def _hue(pos: float) -> RGB:
    red, green, blue = colorsys.hsv_to_rgb(pos % 1, SATURATION, VALUE)
    return (int(red * CHANNEL_MAX), int(green * CHANNEL_MAX), int(blue * CHANNEL_MAX))


def _uniform(leds: list[Cell], colour: RGB) -> dict[Cell, RGB]:
    return {cell: colour for cell in leds}


def _wave_positions(leds: list[Cell], angle: float) -> dict[Cell, float]:
    """Each key's position (0..1) along the ``angle`` direction over the group's box.

    Angle 0 runs left to right along the columns, 90 runs bottom to top.
    """
    radians = math.radians(angle % FULL_TURN_DEGREES)
    dx = round(math.cos(radians), DIRECTION_DIGITS)
    dy = round(-math.sin(radians), DIRECTION_DIGITS)
    projected = {(row, col): col * dx + row * dy for row, col in leds}
    low, high = min(projected.values()), max(projected.values())
    span = high - low
    return {cell: (value - low) / span if span > 0 else NONE for cell, value in projected.items()}


def _wave(effect: KeyEffect, leds: list[Cell], t: float) -> dict[Cell, RGB]:
    sign = -1 if effect.direction == DIRECTION_REVERSE else 1
    phase = t * effect.speed * sign
    positions = _wave_positions(leds, effect.angle)
    return {cell: _blend(effect.palette, pos / effect.width - phase)
            for cell, pos in positions.items()}


def _breathing(effect: KeyEffect, leds: list[Cell], t: float) -> dict[Cell, RGB]:
    cycles = t * effect.speed
    level = (1 - math.cos(FULL_TURN * cycles)) * HALF
    colour = effect.palette[int(cycles) % len(effect.palette)]
    return _uniform(leds, _scaled(colour, level))


def _age_level(t: float, pressed: float, fade: float) -> float:
    """1 at the press, falling to 0 after ``fade`` seconds (0 before the press)."""
    age = t - pressed
    if age < 0 or age > fade:
        return NONE
    return FULL - age / fade


def _reactive(effect: KeyEffect, leds: list[Cell], t: float,
              presses: Sequence[Press]) -> dict[Cell, RGB]:
    levels = dict.fromkeys(leds, NONE)
    for pressed, where in presses:
        level = _age_level(t, pressed, effect.fade)
        for cell in (leds if where is None else [where]):
            if cell in levels:
                levels[cell] = max(levels[cell], level)
    colour = effect.palette[0]
    return {cell: _scaled(colour, level) for cell, level in levels.items()}


def _centroid(leds: list[Cell]) -> tuple[float, float]:
    return (sum(r for r, _ in leds) / len(leds), sum(c for _, c in leds) / len(leds))


def _ring_level(distance: float, radius: float, thickness: float) -> float:
    return max(NONE, FULL - abs(distance - radius) / thickness)


def _ripple(effect: KeyEffect, leds: list[Cell], t: float,
            presses: Sequence[Press]) -> dict[Cell, RGB]:
    levels = dict.fromkeys(leds, NONE)
    thickness = effect.width * RIPPLE_MAX_THICKNESS
    centre = _centroid(leds)
    for pressed, where in presses:
        fade = _age_level(t, pressed, effect.fade)
        if fade <= NONE:
            continue
        radius = (t - pressed) * effect.speed * RIPPLE_KEYS_PER_CYCLE
        origin = centre if where is None else where
        for cell in leds:
            distance = math.dist(cell, origin)
            levels[cell] = max(levels[cell], _ring_level(distance, radius, thickness) * fade)
    colour = effect.palette[0]
    return {cell: _scaled(colour, level) for cell, level in levels.items()}


def _starlight(effect: KeyEffect, leds: list[Cell], rng: random.Random) -> dict[Cell, RGB]:
    colours = {}
    for cell in leds:
        if rng.random() < effect.density:
            colours[cell] = _scaled(rng.choice(effect.palette), rng.random())
        else:
            colours[cell] = BLACK
    return colours


def _render(effect: KeyEffect, leds: list[Cell], t: float, presses: Sequence[Press],
            rng: random.Random) -> dict[Cell, RGB]:
    if effect.effect == EFFECT_WAVE:
        return _wave(effect, leds, t)
    if effect.effect == EFFECT_BREATHING:
        return _breathing(effect, leds, t)
    if effect.effect == EFFECT_SPECTRUM:
        return _uniform(leds, _hue(t * effect.speed))
    if effect.effect == EFFECT_REACTIVE:
        return _reactive(effect, leds, t, presses)
    if effect.effect == EFFECT_RIPPLE:
        return _ripple(effect, leds, t, presses)
    if effect.effect == EFFECT_STARLIGHT:
        return _starlight(effect, leds, rng)
    return _uniform(leds, effect.palette[0])


def render_group(effect: KeyEffect, leds: Iterable[Cell], t_seconds: float,
                 presses: Sequence[Press], rng: random.Random) -> dict[Cell, RGB]:
    """Colours of the group's ``leds`` at ``t_seconds``, scaled by the effect brightness.

    ``presses`` drive reactive (a None position lights the whole group) and
    ripple (a None position starts at the group's centroid); ``rng`` drives
    starlight. An empty group renders nothing.
    """
    cells = list(dict.fromkeys(leds))
    if not cells:
        return {}
    colours = _render(effect, cells, t_seconds, presses, rng)
    return {cell: _scaled(colour, effect.brightness) for cell, colour in colours.items()}
