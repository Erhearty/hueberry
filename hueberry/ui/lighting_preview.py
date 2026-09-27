# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Map the lighting panel's selection to a :class:`Preset` for the LED preview.

The preview is an approximation of the hardware effect: openrazer effects
(breath, starlight, wave, ...) run in the device firmware, so they are drawn
with the closest animator effect and palette rather than reproduced exactly.
A selected preset is shown as-is.
"""

from typing import TYPE_CHECKING, Callable

from PyQt6.QtGui import QColor

from hueberry.backend.effects import (
    DIRECTION_FORWARD, DIRECTION_REVERSE, EFFECT_BREATHE, EFFECT_CYCLE, EFFECT_PER_KEY,
    EFFECT_STATIC, MAX_BRIGHTNESS, RGB, Preset,
)
from hueberry.backend.lighting import WAVE_LEFT

if TYPE_CHECKING:  # avoid a circular import with lighting_panel
    from hueberry.ui.lighting_panel import LightingPanel

PREVIEW_KEY = "preview"  # key of the generated preset
PREVIEW_SPEED = 0.5  # cycles per second of the approximated effect
EFFECT_OFF = "none"  # lighting key that turns the lights off (no preview)
HUE_STEPS = 6  # colours around the hue wheel
HUE_FULL_TURN = 360  # QColor hue range, in degrees
HUE_SATURATION = 255
HUE_VALUE = 255
RGB_CHANNELS = 3

#: Rainbow palette standing in for random / spectrum hardware effects.
HUE_PALETTE: tuple[RGB, ...] = tuple(
    tuple(QColor.fromHsv(step * HUE_FULL_TURN // HUE_STEPS, HUE_SATURATION,
                         HUE_VALUE).getRgb()[:RGB_CHANNELS])
    for step in range(HUE_STEPS)
)

PaletteRule = Callable[["LightingPanel"], tuple[RGB, ...]]


def _colour1(panel: "LightingPanel") -> tuple[RGB, ...]:
    """The primary colour alone."""
    return (panel.colour1_button.colour(),)


def _colours12(panel: "LightingPanel") -> tuple[RGB, ...]:
    """The primary then the secondary colour."""
    return (panel.colour1_button.colour(), panel.colour2_button.colour())


def _hues(_panel: "LightingPanel") -> tuple[RGB, ...]:
    """The rainbow palette."""
    return HUE_PALETTE


#: Lighting effect key -> (preview effect, palette rule).
EFFECT_MAP: dict[str, tuple[str, PaletteRule]] = {
    "static": (EFFECT_STATIC, _colour1),
    "reactive": (EFFECT_STATIC, _colour1),
    "breath_single": (EFFECT_BREATHE, _colour1),
    "pulsate": (EFFECT_BREATHE, _colour1),
    "blinking": (EFFECT_BREATHE, _colour1),
    "starlight_single": (EFFECT_BREATHE, _colour1),
    "breath_dual": (EFFECT_BREATHE, _colours12),
    "starlight_dual": (EFFECT_BREATHE, _colours12),
    "breath_random": (EFFECT_BREATHE, _hues),
    "starlight_random": (EFFECT_BREATHE, _hues),
    "spectrum": (EFFECT_CYCLE, _hues),
    "wave": (EFFECT_PER_KEY, _hues),
}
DEFAULT_MAPPING: tuple[str, PaletteRule] = (EFFECT_STATIC, _colour1)


def _direction(panel: "LightingPanel") -> str:
    """'reverse' for a left wave, else 'forward'."""
    if panel.direction_combo.currentData() == WAVE_LEFT:
        return DIRECTION_REVERSE
    return DIRECTION_FORWARD


def _brightness(panel: "LightingPanel") -> float:
    """The slider as a 0-1 fraction, or full brightness when it is disabled."""
    slider = panel.brightness_slider
    if not slider.isEnabled():
        return MAX_BRIGHTNESS
    return slider.value() / slider.maximum()  # the slider's own range, not the backend's


def preview_preset(panel: "LightingPanel") -> Preset | None:
    """The preset approximating ``panel``'s selection, or None when nothing is lit."""
    selected = panel.selected_preset()
    if selected is not None:
        return selected
    effect = panel.current_effect()
    if effect is None or effect.key == EFFECT_OFF:
        return None
    preview_effect, palette_rule = EFFECT_MAP.get(effect.key, DEFAULT_MAPPING)
    return Preset(key=PREVIEW_KEY, label=effect.label, effect=preview_effect,
                  palette=palette_rule(panel), speed=PREVIEW_SPEED,
                  direction=_direction(panel), brightness=_brightness(panel))
