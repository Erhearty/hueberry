# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Turn every lighting zone of the given devices off (used on shutdown).

Each zone gets the ``none`` effect, or a black ``static`` colour when ``none``
is unsupported. Nothing is recorded in ``device_effects.json``: the next start
reapplies the last recorded effects. Nothing here imports openrazer.
"""

import logging
from typing import Any, Iterable

from hueberry.backend import lighting
from hueberry.backend.devices import ZoneInfo, list_zones

__all__ = ["OFF_COLOUR", "turn_off"]

logger = logging.getLogger(__name__)

OFF_EFFECT = "none"
STATIC_EFFECT = "static"
OFF_COLOUR = (0, 0, 0)  # black: the LEDs look off


def _turn_zone_off(dev: Any, zone: ZoneInfo) -> bool:
    """Switch ``zone`` off; True when a supported way to do so was called."""
    if lighting.is_effect_supported(dev, zone, OFF_EFFECT):
        lighting.apply_effect(dev, zone, OFF_EFFECT)
        return True
    if lighting.is_effect_supported(dev, zone, STATIC_EFFECT):
        zone.obj.static(*OFF_COLOUR)
        return True
    logger.info("Zone %s cannot be turned off (no none/static effect)", zone.key)
    return False


def turn_off(devices: Iterable[Any]) -> int:
    """Turn off every lighting zone of ``devices``; the number of zones turned off.

    A failing zone is logged and skipped; this never raises.
    """
    count = 0
    for dev in devices:
        for zone in list_zones(dev):
            try:
                count += _turn_zone_off(dev, zone)
            except Exception:  # D-Bus / daemon errors must not stop the other zones
                logger.warning("Turning off zone %s failed", zone.key, exc_info=True)
    logger.info("Turned off %d lighting zones", count)
    return count
