# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Worker jobs of the lighting panel (they run off the UI thread).

``lighting_state.shared_lighting_state()`` is looked up at call time, so tests
can monkeypatch it.
"""

import logging
from typing import Any, Callable

from hueberry.backend import device_effects_store, lighting_state
from hueberry.backend.animator_targets import device_serial
from hueberry.backend.devices import ZoneInfo
from hueberry.backend.lighting import apply_effect

logger = logging.getLogger(__name__)


def claim_then_apply(dev: Any, zone: ZoneInfo, effect_key: str, params: dict[str, Any],
                     apply: Callable[..., Any] = apply_effect) -> Any:
    """Worker job: claim ``dev`` for other lighting, then apply an effect.

    Claiming (:meth:`LightingState.claim`) makes an advanced per-key effect
    running on the device let go of it; that may restore the matrix over
    D-Bus, so it runs here rather than on the UI thread. A failed claim is
    logged and never prevents the apply. ``apply`` performs the effect write
    (the backend's ``apply_effect`` unless the caller passes its own). A
    successful apply is recorded in :mod:`hueberry.backend.device_effects_store`
    (OpenRazer cannot read effects back); a failed record is only logged.
    """
    serial = device_serial(dev)
    if serial is not None:
        try:
            lighting_state.shared_lighting_state().claim((serial,))
        except Exception:  # the new effect is still applied
            logger.exception("Could not claim %s for the new effect", serial)
    result = apply(dev, zone, effect_key, params)
    if serial is not None and result:
        _record(serial, zone, effect_key, params)
    return result


def _record(serial: str, zone: ZoneInfo, effect_key: str, params: dict[str, Any]) -> None:
    """Remember the applied effect; failures are logged, never raised."""
    try:
        device_effects_store.save_record(serial, zone.key, effect_key, params)
    except Exception:  # the effect is applied either way
        logger.exception("Could not record effect %s for %s", effect_key, serial)
