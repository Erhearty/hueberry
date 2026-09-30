# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Per-key effects: what one group of keys shows in an advanced preset.

A :class:`KeyEffect` is plain data so it can be saved in
``advanced_presets.json``, edited in the UI and rendered by
:mod:`hueberry.backend.key_effect_render`. Colours are ``(r, g, b)`` tuples
of 0-255 integers, saved as ``'#rrggbb'`` like :class:`effects.Preset`.
Nothing here imports openrazer or Qt.
"""

from dataclasses import dataclass, replace
from typing import Any, Mapping

from hueberry.backend.effects import (
    CHANNEL_MAX, CHANNEL_MIN, CHANNELS, DIRECTION_FORWARD, DIRECTIONS, RGB, PresetError,
    hex_to_rgb, rgb_to_hex,
)

__all__ = ["EFFECT_BREATHING", "EFFECT_LABELS", "EFFECT_REACTIVE", "EFFECT_RIPPLE",
           "EFFECT_SPECTRUM", "EFFECT_STARLIGHT", "EFFECT_STATIC", "EFFECT_TYPES",
           "EFFECT_WAVE", "KeyEffect", "is_animated", "uses_presses"]

EFFECT_STATIC = "static"  # the first palette colour, not animated
EFFECT_WAVE = "wave"  # palette gradient travelling along ``angle``
EFFECT_BREATHING = "breathing"  # the group fades in and out, one colour per breath
EFFECT_SPECTRUM = "spectrum"  # the whole group cycles through every hue
EFFECT_REACTIVE = "reactive"  # a pressed key lights up and fades over ``fade``
EFFECT_RIPPLE = "ripple"  # a ring spreads out from each pressed key
EFFECT_STARLIGHT = "starlight"  # random keys twinkle
EFFECT_LABELS = {EFFECT_STATIC: "Static", EFFECT_WAVE: "Wave",
                 EFFECT_BREATHING: "Breathing", EFFECT_SPECTRUM: "Spectrum",
                 EFFECT_REACTIVE: "Reactive", EFFECT_RIPPLE: "Ripple",
                 EFFECT_STARLIGHT: "Starlight"}
EFFECT_TYPES = tuple(EFFECT_LABELS)
PRESS_EFFECTS = frozenset({EFFECT_REACTIVE, EFFECT_RIPPLE})

MIN_SPEED = 0.0  # cycles per second (ripple: see key_effect_render)
MAX_SPEED = 10.0
MIN_BRIGHTNESS = 0.0
MAX_BRIGHTNESS = 1.0
MIN_ANGLE = 0.0  # degrees, anticlockwise; 0 travels left to right
MAX_ANGLE = 360.0
MIN_WIDTH = 0.05  # wave: gradient length as a fraction of the group; ripple: ring size
MAX_WIDTH = 1.0
MIN_DENSITY = 0.0  # starlight: chance a key twinkles in one frame
MAX_DENSITY = 1.0
MIN_FADE = 0.1  # seconds a press stays visible (reactive, ripple)
MAX_FADE = 10.0
MIN_PALETTE = 1
MAX_PALETTE = 16
DEFAULT_COLOUR: RGB = (0, 255, 0)
DEFAULT_SPEED = 1.0
DEFAULT_ANGLE = 0.0
DEFAULT_WIDTH = 0.5
DEFAULT_DENSITY = 0.1
DEFAULT_FADE = 1.0


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise PresetError(message)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _in_range(value: Any, low: float, high: float) -> bool:
    return _is_number(value) and low <= value <= high


def _valid_colour(colour: Any) -> bool:
    return (isinstance(colour, tuple) and len(colour) == CHANNELS
            and all(isinstance(c, int) and CHANNEL_MIN <= c <= CHANNEL_MAX for c in colour))


def uses_presses(effect: str) -> bool:
    """True when ``effect`` reacts to key presses."""
    return effect in PRESS_EFFECTS


def is_animated(effect: str) -> bool:
    """False when ``effect`` never changes over time."""
    return effect != EFFECT_STATIC


@dataclass(frozen=True)
class KeyEffect:
    """The effect of one key group and its parameters."""

    effect: str = EFFECT_STATIC
    palette: tuple[RGB, ...] = (DEFAULT_COLOUR,)
    speed: float = DEFAULT_SPEED
    brightness: float = MAX_BRIGHTNESS
    direction: str = DIRECTION_FORWARD
    angle: float = DEFAULT_ANGLE
    width: float = DEFAULT_WIDTH
    density: float = DEFAULT_DENSITY
    fade: float = DEFAULT_FADE

    def validate(self) -> None:
        """Raise PresetError describing the first invalid field."""
        _check(self.effect in EFFECT_TYPES, f"unknown effect {self.effect!r}")
        _check(isinstance(self.palette, tuple) and MIN_PALETTE <= len(self.palette) <= MAX_PALETTE,
               f"a palette has {MIN_PALETTE} to {MAX_PALETTE} colours")
        _check(all(_valid_colour(colour) for colour in self.palette), "invalid palette colour")
        _check(isinstance(self.direction, str) and self.direction in DIRECTIONS,
               f"direction must be one of {DIRECTIONS}")
        self._validate_numbers()

    def _validate_numbers(self) -> None:
        ranges = (("speed", MIN_SPEED, MAX_SPEED), ("brightness", MIN_BRIGHTNESS, MAX_BRIGHTNESS),
                  ("angle", MIN_ANGLE, MAX_ANGLE), ("width", MIN_WIDTH, MAX_WIDTH),
                  ("density", MIN_DENSITY, MAX_DENSITY), ("fade", MIN_FADE, MAX_FADE))
        for name, low, high in ranges:
            _check(_in_range(getattr(self, name), low, high), f"{name} must be {low} to {high}")

    def with_changes(self, **changes: Any) -> "KeyEffect":
        """A copy with ``changes`` applied (not validated)."""
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready form."""
        return {"effect": self.effect, "palette": [rgb_to_hex(c) for c in self.palette],
                "speed": self.speed, "brightness": self.brightness,
                "direction": self.direction, "angle": self.angle, "width": self.width,
                "density": self.density, "fade": self.fade}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "KeyEffect":
        """Build and validate an effect from its saved form; PresetError when invalid.

        Missing optional parameters take their defaults; ``effect`` and
        ``palette`` are required.
        """
        _check(isinstance(data, Mapping), "a key effect must be an object")
        palette = data.get("palette")
        _check(isinstance(palette, list), "a key effect palette must be a list")
        _check("effect" in data, "a key effect is missing 'effect'")
        defaults = cls(effect=data["effect"])
        fields = ("speed", "brightness", "direction", "angle", "width", "density", "fade")
        values = {name: data.get(name, getattr(defaults, name)) for name in fields}
        effect = cls(effect=data["effect"], palette=tuple(hex_to_rgb(t) for t in palette),
                     **values)
        effect.validate()
        return effect
