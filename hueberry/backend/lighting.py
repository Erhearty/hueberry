# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Lighting effects and brightness for a device's lighting zones.

Every function takes the device object (for capability checks) and a
:class:`~hueberry.backend.devices.ZoneInfo` (whose ``obj`` is ``dev.fx`` for the
main zone or a ``dev.fx.misc.<zone>`` object for misc zones). Nothing here
imports openrazer; the objects are passed in by the caller.
"""

import logging
from dataclasses import dataclass
from typing import Any, Mapping

from hueberry.backend.devices import MAIN_ZONE_KEY, ZoneInfo

logger = logging.getLogger(__name__)

# Parameter names accepted in ``apply_effect``'s ``params`` mapping.
PARAM_COLOUR1 = "colour1"
PARAM_COLOUR2 = "colour2"
PARAM_TIME = "time"
PARAM_DIRECTION = "direction"

# Reactive / starlight speed values (same numbers as openrazer's constants).
REACTIVE_SHORT = 1
REACTIVE_MED = 2
REACTIVE_LONG = 3
TIME_VALUES = (REACTIVE_SHORT, REACTIVE_MED, REACTIVE_LONG)

# Wave directions (openrazer WAVE_RIGHT / WAVE_LEFT).
WAVE_RIGHT = 1
WAVE_LEFT = 2
DIRECTION_VALUES = (WAVE_RIGHT, WAVE_LEFT)

COLOUR_COMPONENTS = 3
COLOUR_MIN = 0
COLOUR_MAX = 255

BRIGHTNESS_MIN = 0.0
BRIGHTNESS_MAX = 100.0
BRIGHTNESS_CAPABILITY = "brightness"


class LightingError(Exception):
    """Raised when an effect is unsupported or the device call fails."""


@dataclass(frozen=True)
class Effect:
    """One lighting effect: label, capability suffix, method and parameters."""

    key: str
    label: str
    capability_suffix: str
    method: str
    params: tuple[str, ...] = ()


_EFFECT_LIST = (
    Effect("none", "Off", "none", "none"),
    Effect("static", "Static", "static", "static", (PARAM_COLOUR1,)),
    Effect("spectrum", "Spectrum", "spectrum", "spectrum"),
    Effect("breath_single", "Breath (single)", "breath_single", "breath_single",
           (PARAM_COLOUR1,)),
    Effect("breath_dual", "Breath (dual)", "breath_dual", "breath_dual",
           (PARAM_COLOUR1, PARAM_COLOUR2)),
    Effect("breath_random", "Breath (random)", "breath_random", "breath_random"),
    Effect("reactive", "Reactive", "reactive", "reactive", (PARAM_COLOUR1, PARAM_TIME)),
    Effect("wave", "Wave", "wave", "wave", (PARAM_DIRECTION,)),
    Effect("starlight_single", "Starlight (single)", "starlight_single",
           "starlight_single", (PARAM_COLOUR1, PARAM_TIME)),
    Effect("starlight_dual", "Starlight (dual)", "starlight_dual", "starlight_dual",
           (PARAM_COLOUR1, PARAM_COLOUR2, PARAM_TIME)),
    Effect("starlight_random", "Starlight (random)", "starlight_random",
           "starlight_random", (PARAM_TIME,)),
    Effect("blinking", "Blinking", "blinking", "blinking", (PARAM_COLOUR1,)),
    Effect("pulsate", "Pulsate", "pulsate", "pulsate", (PARAM_COLOUR1,)),
)

#: Effect key -> :class:`Effect`, in display order.
EFFECTS: dict[str, Effect] = {effect.key: effect for effect in _EFFECT_LIST}


def _has(dev: Any, capability: str) -> bool:
    try:
        return bool(dev.has(capability))
    except Exception:  # D-Bus errors
        logger.warning("Could not query capability %s", capability, exc_info=True)
        return False


def _has_method(obj: Any, name: str) -> bool:
    try:
        return callable(getattr(obj, name, None))
    except Exception:  # D-Bus errors while resolving the attribute
        logger.warning("Could not resolve method %s", name, exc_info=True)
        return False


def is_effect_supported(dev: Any, zone: ZoneInfo, key: str) -> bool:
    """Return True if ``dev`` advertises ``key`` for ``zone`` and the method exists."""
    effect = EFFECTS.get(key)
    if effect is None:
        return False
    capability = f"{zone.capability_prefix}_{effect.capability_suffix}"
    return _has(dev, capability) and _has_method(zone.obj, effect.method)


def supported_effects(dev: Any, zone: ZoneInfo) -> list[Effect]:
    """List effects usable on ``zone`` of ``dev``, in :data:`EFFECTS` order.

    An effect is included when ``dev.has(f"{zone.capability_prefix}_{suffix}")``
    is true and ``zone.obj`` has a callable method of the effect's name.
    """
    return [effect for effect in _EFFECT_LIST if is_effect_supported(dev, zone, effect.key)]


def validate_colour(colour: Any) -> tuple[int, int, int]:
    """Return ``colour`` as an (r, g, b) tuple or raise ValueError."""
    if not isinstance(colour, (tuple, list)) or len(colour) != COLOUR_COMPONENTS:
        raise ValueError(f"Colour must be an (r, g, b) tuple, got {colour!r}")
    for component in colour:
        if isinstance(component, bool) or not isinstance(component, int):
            raise ValueError(f"Colour components must be integers, got {colour!r}")
        if not COLOUR_MIN <= component <= COLOUR_MAX:
            raise ValueError(f"Colour components must be 0-255, got {colour!r}")
    return (colour[0], colour[1], colour[2])


def _validate_choice(name: str, value: Any, allowed: tuple[int, ...]) -> int:
    if isinstance(value, bool) or value not in allowed:
        raise ValueError(f"Invalid {name} {value!r}; expected one of {allowed}")
    return int(value)


def _build_args(effect: Effect, params: Mapping[str, Any]) -> list[Any]:
    """Flatten ``params`` into the positional arguments of the effect method."""
    args: list[Any] = []
    for name in effect.params:
        if name not in params:
            raise ValueError(f"Effect {effect.key!r} needs parameter {name!r}")
        value = params[name]
        if name in (PARAM_COLOUR1, PARAM_COLOUR2):
            args.extend(validate_colour(value))
        elif name == PARAM_TIME:
            args.append(_validate_choice(name, value, TIME_VALUES))
        else:
            args.append(_validate_choice(name, value, DIRECTION_VALUES))
    return args


def apply_effect(dev: Any, zone: ZoneInfo, key: str,
                 params: Mapping[str, Any] | None = None) -> bool:
    """Apply effect ``key`` to ``zone`` with ``params`` (see ``PARAM_*`` names).

    Raises ValueError for an unknown key or invalid parameters and
    LightingError when the effect is unsupported or the device call fails.
    Returns the method's result as a bool; ``None`` (the real client's return
    value) counts as success.
    """
    effect = EFFECTS.get(key)
    if effect is None:
        raise ValueError(f"Unknown effect {key!r}")
    if not is_effect_supported(dev, zone, key):
        raise LightingError(f"Effect {key!r} is not supported on zone {zone.key!r}")
    args = _build_args(effect, params or {})
    try:
        result = getattr(zone.obj, effect.method)(*args)
    except Exception as exc:  # D-Bus / NotImplementedError / daemon validation
        logger.error("Applying %s on %s failed", key, zone.key, exc_info=True)
        raise LightingError(f"Could not apply {key!r} on {zone.key!r}: {exc}") from exc
    return True if result is None else bool(result)


def _brightness_target(dev: Any, zone: ZoneInfo) -> Any:
    return dev if zone.key == MAIN_ZONE_KEY else zone.obj


def supports_brightness(dev: Any, zone: ZoneInfo) -> bool:
    """Check 'brightness' (main) or f'{prefix}_brightness' (misc zones)."""
    if zone.key == MAIN_ZONE_KEY:
        return _has(dev, BRIGHTNESS_CAPABILITY)
    return _has(dev, f"{zone.capability_prefix}_{BRIGHTNESS_CAPABILITY}")


def clamp_brightness(value: float) -> float:
    """Clamp ``value`` to BRIGHTNESS_MIN..BRIGHTNESS_MAX."""
    return max(BRIGHTNESS_MIN, min(BRIGHTNESS_MAX, float(value)))


def get_brightness(dev: Any, zone: ZoneInfo) -> float:
    """Read the zone's brightness (0-100); failures raise LightingError."""
    try:
        value = _brightness_target(dev, zone).brightness
        return clamp_brightness(value)
    except Exception as exc:  # D-Bus / NotImplementedError / bad value
        logger.error("Reading brightness of %s failed", zone.key, exc_info=True)
        raise LightingError(f"Could not read brightness of {zone.key!r}: {exc}") from exc


def set_brightness(dev: Any, zone: ZoneInfo, value: float) -> float:
    """Set the zone's brightness clamped to 0-100 and return the value applied."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Brightness must be a number, got {value!r}")
    applied = clamp_brightness(value)
    try:
        _brightness_target(dev, zone).brightness = applied
    except Exception as exc:  # D-Bus / NotImplementedError
        logger.error("Setting brightness of %s failed", zone.key, exc_info=True)
        raise LightingError(f"Could not set brightness of {zone.key!r}: {exc}") from exc
    return applied
