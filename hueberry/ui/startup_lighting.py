# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Reapply the recorded whole-device effects once per device after a start.

Shutdown turns every LED off without recording it, so the first time a device
shows up the effects in ``device_effects.json`` are applied again directly
(no lighting job, no new record).
"""

import logging
from typing import Any, Iterable

from hueberry.backend import device_effects_store, lighting
from hueberry.backend.animator_targets import device_serial
from hueberry.backend.devices import ZoneInfo, list_zones

__all__ = ["reapply_recorded", "reset"]

logger = logging.getLogger(__name__)

_done: set[str] = set()  # serials already reapplied in this process


def reset() -> None:
    """Forget which devices were reapplied (for tests)."""
    _done.clear()


def _reapply_zone(dev: Any, serial: str, zone: ZoneInfo) -> None:
    """Apply the effect recorded for ``zone``; failures are logged."""
    record = device_effects_store.load_record(serial, zone.key)
    if record is None:
        return
    effect_key, params = record
    try:
        lighting.apply_effect(dev, zone, effect_key, params)
    except Exception:  # unsupported effect / D-Bus errors must not break the start
        logger.warning("Reapplying %s on %s/%s failed", effect_key, serial, zone.key,
                       exc_info=True)
        return
    logger.info("Reapplied %s on %s/%s", effect_key, serial, zone.key)


def reapply_recorded(devices: Iterable[Any]) -> None:
    """Reapply recorded effects on each device not seen before; never raises."""
    for dev in devices:
        serial = device_serial(dev)
        if serial is None or serial in _done:
            continue
        _done.add(serial)
        for zone in list_zones(dev):
            try:
                _reapply_zone(dev, serial, zone)
            except Exception:  # a broken zone must not stop the others
                logger.warning("Reapplying lighting of %s/%s failed", serial, zone.key,
                               exc_info=True)
