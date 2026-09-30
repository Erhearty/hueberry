# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Build the LED preview entry of one device (its serial, name, type and LED shape)."""

import logging
from typing import Any

from hueberry.backend.animator_targets import build_target
from hueberry.ui.led_preview import PreviewDevice

__all__ = ["preview_device"]

logger = logging.getLogger(__name__)


def preview_device(dev: Any, info: Any) -> PreviewDevice | None:
    """The preview entry of a ``(device, DeviceInfo)`` pair, or None without LEDs to show."""
    try:
        target = build_target(dev)
    except Exception:  # D-Bus errors must not break the page
        logger.warning("Could not read the LED shape of %s", info.serial, exc_info=True)
        return None
    if target is None:
        return None
    return PreviewDevice(info.serial, info.name or info.serial, info.type, target.shape())
