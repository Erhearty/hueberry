# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Device side of the animator: how one device is painted with a rendered frame.

A :class:`Target` wraps one device object: a per-key matrix painted through
``fx.advanced``, or every zone that supports a static colour painted with
one colour. Rendering errors are classified here (stale device, not ready,
unexpected) so one misbehaving device never stops the others. Nothing here
imports openrazer or Qt: device objects are passed in by the caller.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from hueberry.backend import presets
from hueberry.backend.devices import MATRIX_CAPABILITY, list_zones
from hueberry.backend.effects import Frame
from hueberry.backend.led_layout import DeviceShape
from hueberry.backend.lighting import is_effect_supported

logger = logging.getLogger(__name__)

STATIC_EFFECT = "static"
KIND_MATRIX = "matrix"  # per-key frame through fx.advanced
KIND_ZONES = "zones"  # one colour through zone.static
FIRST = 0  # a zone device's frame is 1x1: its only LED is frame[0][0]


@dataclass
class Target:
    """One animated device and how to paint it."""

    serial: str
    kind: str
    advanced: Any = None
    rows: int = 0
    cols: int = 0
    zones: list = field(default_factory=list)
    applied: bool = False  # a frame was painted (non-animated presets paint once)
    paused: bool = False  # stale device object; resumes on refresh()
    active: bool = True  # False once stopped or replaced; never rendered again
    warned: bool = False  # one warning per target for unexpected errors

    def shape(self) -> DeviceShape:
        """The device's LED shape for :mod:`hueberry.backend.led_layout`."""
        if self.kind == KIND_MATRIX:
            return DeviceShape.of_matrix(self.serial, self.rows, self.cols)
        return DeviceShape.of_zones(self.serial)


def device_serial(dev: Any) -> str | None:
    """The device's serial, or None when it cannot be read."""
    try:
        return str(dev.serial)
    except Exception:  # D-Bus errors
        logger.warning("Could not read device serial", exc_info=True)
        return None


def _static_zones(dev: Any) -> list:
    return [zone.obj for zone in list_zones(dev) if is_effect_supported(dev, zone, STATIC_EFFECT)]


def _matrix_target(serial: str, dev: Any) -> Target | None:
    try:
        advanced = dev.fx.advanced if dev.has(MATRIX_CAPABILITY) else None
        if advanced is None:
            return None
        return Target(serial, KIND_MATRIX, advanced=advanced,
                      rows=int(advanced.rows), cols=int(advanced.cols))
    except Exception:  # D-Bus errors / no advanced matrix
        logger.warning("No usable key matrix on %s", serial, exc_info=True)
        return None


def build_target(dev: Any) -> Target | None:
    """Describe how to paint ``dev``, or None when it cannot show a preset."""
    serial = device_serial(dev)
    if serial is None:
        return None
    target = _matrix_target(serial, dev)
    if target is not None:
        return target
    zones = _static_zones(dev)
    return Target(serial, KIND_ZONES, zones=zones) if zones else None


def supports(dev: Any) -> bool:
    """True when lighting presets can be shown on ``dev``."""
    return dev is not None and build_target(dev) is not None


def _paint(target: Target, frame: Frame) -> None:
    if target.kind == KIND_MATRIX:
        matrix = target.advanced.matrix
        for row in range(target.rows):
            for col in range(target.cols):
                matrix[row, col] = frame[row][col]
        target.advanced.draw()
        return
    colour = frame[FIRST][FIRST]
    for zone in target.zones:
        zone.static(*colour)


def render_safely(target: Target, frame: Frame) -> None:
    """Paint one frame; pause the target on stale errors, keep it otherwise."""
    try:
        _paint(target, frame)
        target.applied = True
    except Exception as exc:  # D-Bus / sysfs errors from the device
        if presets.is_not_ready_error(exc):
            logger.debug("Device %s not ready, retrying: %s", target.serial, exc)
        elif presets.is_stale_error(exc):
            logger.info("Device %s is stale, pausing until reload", target.serial)
            target.paused = True
        elif not target.warned:
            logger.warning("Animating %s failed", target.serial, exc_info=True)
            target.warned = True


def restore(target: Target) -> None:
    """Ask a matrix device for its last hardware effect (zones keep their colour)."""
    if target.kind != KIND_MATRIX:
        return
    try:
        target.advanced.restore()
    except Exception:  # D-Bus errors; the device may be gone
        logger.warning("Could not restore lighting of %s", target.serial, exc_info=True)
