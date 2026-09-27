# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Worker jobs of the lighting panel (they run off the UI thread).

``lighting_state.shared_lighting_state()`` is looked up at call time, so tests
can monkeypatch it.
"""

import logging
from typing import Any, Callable

from hueberry.backend import animator, lighting_state
from hueberry.backend.devices import ZoneInfo
from hueberry.backend.lighting import apply_effect

logger = logging.getLogger(__name__)


def stop_preset_then_apply(dev: Any, zone: ZoneInfo, effect_key: str, params: dict[str, Any],
                           apply: Callable[..., Any] = apply_effect) -> Any:
    """Worker job: stop and forget a preset animation on ``dev``, then apply an effect.

    Stopping may wait for one animation frame and restores the matrix over
    D-Bus, so it runs here rather than on the UI thread. A failed stop is
    logged and never prevents the apply. ``apply`` performs the effect write
    (the backend's ``apply_effect`` unless the caller passes its own).
    """
    serial = animator.device_serial(dev)
    if serial is not None:
        try:
            lighting_state.shared_lighting_state().stop_device(serial)
        except Exception:  # the new effect is still applied
            logger.exception("Could not stop the running preset on %s", serial)
    return apply(dev, zone, effect_key, params)
