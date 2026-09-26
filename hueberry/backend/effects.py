# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Lighting presets and the pure maths that turns them into LED colours.

A :class:`Preset` is plain data (palette, effect type, speed, direction,
brightness, wave width) so it can be saved to presets.json, edited in the
UI and rendered by the animator from one definition. Nothing here imports
openrazer or PyQt6. Colours are ``(r, g, b)`` tuples of 0-255 integers; a
run's *phase* is a fraction of one effect cycle (only ``phase % 1`` matters).
"""

import math
import re
from dataclasses import dataclass, replace
from typing import Any, Mapping

from hueberry.backend.led_layout import Layout, Placement

RGB = tuple[int, int, int]
#: A rendered device frame: rows of LED colours (a zone device is 1x1).
Frame = tuple[tuple[RGB, ...], ...]

EFFECT_WAVE = "wave"  # palette-coloured crest travelling diagonally
EFFECT_BREATHE = "breathe"  # every LED fades in and out, one palette colour per breath
EFFECT_CYCLE = "cycle"  # every LED steps through the palette at full brightness
EFFECT_STATIC = "static"  # the first palette colour on every LED, not animated
EFFECT_PER_KEY = "per_key"  # palette stepped key by key across the grid, scrolling
EFFECT_ROTATION = "rotation"  # palette spinning around the centre of the grid
EFFECT_LABELS = {EFFECT_WAVE: "Wave", EFFECT_BREATHE: "Breathe",
                 EFFECT_CYCLE: "Colour cycle", EFFECT_STATIC: "Static",
                 EFFECT_PER_KEY: "Per-key colours", EFFECT_ROTATION: "Rotation"}
EFFECT_TYPES = tuple(EFFECT_LABELS)

DIRECTION_FORWARD = "forward"
DIRECTION_REVERSE = "reverse"
DIRECTIONS = (DIRECTION_FORWARD, DIRECTION_REVERSE)
FORWARD_SIGN = 1
REVERSE_SIGN = -1
_DIRECTION_SIGNS = {DIRECTION_FORWARD: FORWARD_SIGN, DIRECTION_REVERSE: REVERSE_SIGN}
MIN_SPEED = 0.0  # cycles per second; 0 freezes the effect
MAX_SPEED = 10.0
MIN_BRIGHTNESS = 0.0
MAX_BRIGHTNESS = 1.0
MIN_WIDTH = 0.05  # distance (in cycles) over which a wave fades to black
MAX_WIDTH = 1.0
MIN_PALETTE = 1
MAX_PALETTE = 16
MAX_LABEL_LENGTH = 64
STATIC_COLOUR_INDEX = 0  # a static preset shows the first palette colour
CHANNEL_MIN = 0
CHANNEL_MAX = 255
CHANNELS = 3
HEX_BASE = 16
HEX_CHANNEL_WIDTH = 2
HEX_PREFIX = "#"
HEX_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")
KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
PHASE_DIGITS = 12  # rounding of the per-frame step: 2.4 cycles/s at 60 fps is exactly 0.04
FULL_TURN = 2 * math.pi
HALF = 0.5


class PresetError(ValueError):
    """A preset (or its saved form) is invalid."""


def hex_to_rgb(text: str) -> RGB:
    """Convert ``'#rrggbb'`` to an ``(r, g, b)`` tuple; PresetError when malformed."""
    if not isinstance(text, str) or not HEX_PATTERN.fullmatch(text):
        raise PresetError(f"invalid colour {text!r} (expected #rrggbb)")
    digits = text.removeprefix(HEX_PREFIX)
    channels = [int(digits[index:index + HEX_CHANNEL_WIDTH], HEX_BASE)
                for index in range(0, CHANNELS * HEX_CHANNEL_WIDTH, HEX_CHANNEL_WIDTH)]
    return (channels[0], channels[1], channels[2])


def rgb_to_hex(colour: RGB) -> str:
    """Convert an ``(r, g, b)`` tuple to ``'#rrggbb'``."""
    red, green, blue = colour
    return f"{HEX_PREFIX}{red:02x}{green:02x}{blue:02x}"


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise PresetError(message)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _valid_colour(colour: Any) -> bool:
    return (isinstance(colour, tuple) and len(colour) == CHANNELS
            and all(isinstance(c, int) and CHANNEL_MIN <= c <= CHANNEL_MAX for c in colour))


@dataclass(frozen=True)
class Preset:
    """A named lighting preset; ``builtin`` ones ship with Hueberry and are read-only."""

    key: str
    label: str
    effect: str
    palette: tuple[RGB, ...]
    speed: float = 1.0  # cycles per second
    direction: str = DIRECTION_FORWARD
    brightness: float = MAX_BRIGHTNESS
    width: float = MAX_WIDTH
    builtin: bool = False

    def validate(self) -> None:
        """Raise PresetError describing the first invalid field."""
        _check(isinstance(self.key, str) and bool(KEY_PATTERN.fullmatch(self.key)),
               f"invalid preset key {self.key!r}")
        _check(isinstance(self.label, str) and bool(self.label.strip()), "a preset needs a name")
        _check(len(self.label) <= MAX_LABEL_LENGTH,
               f"preset names are at most {MAX_LABEL_LENGTH} characters")
        _check(self.effect in EFFECT_TYPES, f"unknown effect {self.effect!r}")
        _check(isinstance(self.palette, tuple) and MIN_PALETTE <= len(self.palette) <= MAX_PALETTE,
               f"a palette has {MIN_PALETTE} to {MAX_PALETTE} colours")
        _check(all(_valid_colour(colour) for colour in self.palette), "invalid palette colour")
        self._validate_numbers()

    def _validate_numbers(self) -> None:
        _check(_is_number(self.speed) and MIN_SPEED <= self.speed <= MAX_SPEED,
               f"speed must be {MIN_SPEED} to {MAX_SPEED} cycles per second")
        _check(isinstance(self.direction, str) and self.direction in DIRECTIONS,
               f"direction must be one of {DIRECTIONS}")
        _check(_is_number(self.brightness)
               and MIN_BRIGHTNESS <= self.brightness <= MAX_BRIGHTNESS,
               f"brightness must be {MIN_BRIGHTNESS} to {MAX_BRIGHTNESS}")
        _check(_is_number(self.width) and MIN_WIDTH <= self.width <= MAX_WIDTH,
               f"wave width must be {MIN_WIDTH} to {MAX_WIDTH}")

    def with_changes(self, **changes: Any) -> "Preset":
        """A copy with ``changes`` applied (not validated)."""
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready form (``builtin`` is never saved)."""
        return {"key": self.key, "label": self.label, "effect": self.effect,
                "palette": [rgb_to_hex(colour) for colour in self.palette],
                "speed": self.speed, "direction": self.direction,
                "brightness": self.brightness, "width": self.width}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Preset":
        """Build and validate a user preset from its saved form; PresetError when invalid."""
        _check(isinstance(data, Mapping), "a preset must be an object")
        palette = data.get("palette")
        _check(isinstance(palette, list), "a preset palette must be a list")
        try:
            preset = cls(key=data["key"], label=data["label"], effect=data["effect"],
                         palette=tuple(hex_to_rgb(text) for text in palette),
                         speed=data["speed"], direction=data["direction"],
                         brightness=data["brightness"], width=data.get("width", MAX_WIDTH))
        except KeyError as exc:
            raise PresetError(f"preset is missing {exc}") from exc
        preset.validate()
        return preset


def palette_colour_at(palette: tuple[RGB, ...], pos: float) -> RGB:
    """Palette colour at cycle position ``pos`` (stepwise, no blending)."""
    count = len(palette)
    return palette[int((pos % 1) * count) % count]


def crest_brightness(pos: float, phase: float, width: float) -> float:
    """Brightness (0..1) at ``pos`` when the crest is at ``phase``.

    The distance to the crest wraps around the cycle and the fall-off is
    squared, so LEDs at the crest are full brightness.
    """
    distance = abs(pos - phase % 1)
    distance = min(distance, 1 - distance)
    return max(0.0, 1 - distance / width) ** 2


def _scaled(colour: RGB, level: float, master: float) -> RGB:
    red, green, blue = colour
    return (int(red * level * master), int(green * level * master), int(blue * level * master))


def _breath_level(phase: float, count: int) -> float:
    """0..1 intensity; one full breath per palette colour."""
    return (1 - math.cos(FULL_TURN * (phase % 1) * count)) * HALF


def grid_angle(layout: Layout, placement: Placement, row: int, col: int) -> float:
    """Angle (fraction of a turn, 0..1) of a device LED around the grid centre."""
    grid_row, grid_col = placement.grid_cell(row, col)
    centre_row = (layout.rows - 1) * HALF
    centre_col = (layout.cols - 1) * HALF
    return (math.atan2(grid_row - centre_row, grid_col - centre_col) / FULL_TURN) % 1


def led_colour(preset: Preset, pos: float, phase: float, hue_pos: float | None = None,
               angle: float = 0.0) -> RGB:
    """Colour of an LED at grid position ``pos`` (0..1) at ``phase``.

    ``hue_pos`` (default ``pos``) is where the LED samples the palette; see
    :meth:`hueberry.backend.led_layout.Layout.hue_position`. ``angle`` (see
    :func:`grid_angle`) is only used by the rotation effect.
    """
    palette, master = preset.palette, preset.brightness
    hue = pos if hue_pos is None else hue_pos
    if preset.effect == EFFECT_WAVE:
        base = palette_colour_at(palette, (hue + phase) % 1)
        return _scaled(base, crest_brightness(pos, phase, preset.width), master)
    if preset.effect == EFFECT_BREATHE:
        base = palette_colour_at(palette, phase)
        return _scaled(base, _breath_level(phase, len(palette)), master)
    if preset.effect == EFFECT_CYCLE:
        base = palette_colour_at(palette, phase)
    elif preset.effect == EFFECT_PER_KEY:
        base = palette_colour_at(palette, hue + phase)
    elif preset.effect == EFFECT_ROTATION:
        base = palette_colour_at(palette, angle + phase)
    else:
        base = palette[STATIC_COLOUR_INDEX]
    return _scaled(base, MAX_BRIGHTNESS, master)


def _render_placement(preset: Preset, layout: Layout, placement: Placement,
                      phase: float) -> Frame:
    rows = []
    for row in range(placement.led_rows):
        colours = []
        for col in range(placement.led_cols):
            pos = layout.position(placement, row, col)
            angle = grid_angle(layout, placement, row, col)
            colours.append(led_colour(preset, pos, phase, layout.hue_position(placement, pos),
                                      angle))
        rows.append(tuple(colours))
    return tuple(rows)


def render_run(preset: Preset, layout: Layout, phase: float) -> dict[str, Frame]:
    """Frames of every device of a run, keyed by serial."""
    return {placement.serial: _render_placement(preset, layout, placement, phase)
            for placement in layout.placements}


def is_animated(preset: Preset) -> bool:
    """False when the preset's frames do not change over time."""
    return preset.effect != EFFECT_STATIC


def phase_step(preset: Preset, fps: float) -> float:
    """Signed phase advance per frame at ``fps`` frames per second."""
    return round(preset.speed / fps, PHASE_DIGITS) * _DIRECTION_SIGNS[preset.direction]


def advance_phase(preset: Preset, phase: float, fps: float) -> float:
    """Phase of the next frame (wrapped to 0..1)."""
    return (phase + phase_step(preset, fps)) % 1
