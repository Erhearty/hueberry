# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Read-only descriptions of OpenRazer devices and their lighting zones."""

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

UNKNOWN = "Unknown"
LIGHTING_PREFIX = "lighting"
MAIN_ZONE_KEY = "main"
MAIN_ZONE_LABEL = "Main"
MATRIX_CAPABILITY = "lighting_led_matrix"
DPI_CAPABILITY = "dpi"

# (fx.misc attribute, human label, capability zone name used by openrazer)
MISC_ZONES = (
    ("logo", "Logo", "logo"),
    ("scroll_wheel", "Scroll wheel", "scroll"),
    ("left", "Left side", "left"),
    ("right", "Right side", "right"),
    ("backlight", "Backlight", "backlight"),
    ("charging", "Charging", "charging"),
    ("fast_charging", "Fast charging", "fast_charging"),
    ("fully_charged", "Fully charged", "fully_charged"),
)


@dataclass(frozen=True)
class DeviceInfo:
    """Static description of a device, safe to display."""

    name: str
    type: str
    serial: str
    firmware_version: str
    driver_version: str
    has_matrix: bool
    is_mouse: bool


@dataclass(frozen=True)
class ZoneInfo:
    """A lighting zone: key, label, capability prefix and the fx object."""

    key: str
    label: str
    capability_prefix: str
    obj: Any


def _read_text(dev: Any, attr: str) -> str:
    try:
        return str(getattr(dev, attr))
    except Exception:  # D-Bus / NotImplementedError / attribute errors
        logger.warning("Could not read %s from device", attr, exc_info=True)
        return UNKNOWN


def _has(dev: Any, capability: str) -> bool:
    try:
        return bool(dev.has(capability))
    except Exception:  # D-Bus errors
        logger.warning("Could not query capability %s", capability, exc_info=True)
        return False


def describe_device(dev: Any) -> DeviceInfo:
    """Build a DeviceInfo; unreadable fields become ``'Unknown'``."""
    return DeviceInfo(
        name=_read_text(dev, "name"),
        type=_read_text(dev, "type"),
        serial=_read_text(dev, "serial"),
        firmware_version=_read_text(dev, "firmware_version"),
        driver_version=_read_text(dev, "driver_version"),
        has_matrix=_has(dev, MATRIX_CAPABILITY),
        is_mouse=_has(dev, DPI_CAPABILITY),
    )


def _misc_zone(misc: Any, attr: str) -> Any:
    try:
        return getattr(misc, attr, None)
    except Exception:  # D-Bus errors
        logger.warning("Could not read zone %s", attr, exc_info=True)
        return None


def list_zones(dev: Any) -> list[ZoneInfo]:
    """List the device's lighting zones: 'main' (if supported) then misc zones."""
    zones: list[ZoneInfo] = []
    try:
        fx = dev.fx
    except Exception:  # D-Bus / missing fx
        logger.warning("Device has no readable fx", exc_info=True)
        return zones
    if _has(dev, LIGHTING_PREFIX):
        zones.append(ZoneInfo(MAIN_ZONE_KEY, MAIN_ZONE_LABEL, LIGHTING_PREFIX, fx))
    misc = _misc_zone(fx, "misc")
    if misc is None:
        return zones
    for attr, label, cap_zone in MISC_ZONES:
        obj = _misc_zone(misc, attr)
        if obj is not None:
            zones.append(ZoneInfo(attr, label, f"{LIGHTING_PREFIX}_{cap_zone}", obj))
    return zones
