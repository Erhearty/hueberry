# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 RazerUI contributors
"""Mouse-specific controls (DPI and polling rate) for a device object."""

import logging
from typing import Any

logger = logging.getLogger(__name__)

MIN_DPI = 100
FALLBACK_POLL_RATES = (125, 500, 1000)
DPI_CAPABILITY = "dpi"
AVAILABLE_DPI_CAPABILITY = "available_dpi"
POLL_RATE_CAPABILITY = "poll_rate"
SUPPORTED_POLL_RATES_CAPABILITY = "supported_poll_rates"


class MouseError(Exception):
    """Raised when a mouse setting cannot be read or written."""


class MouseControls:
    """DPI and polling-rate access for one mouse device (openrazer RazerMouse)."""

    def __init__(self, dev: Any) -> None:
        self._dev = dev

    def _has(self, capability: str) -> bool:
        try:
            return bool(self._dev.has(capability))
        except Exception:  # D-Bus errors
            logger.warning("Could not query capability %s", capability, exc_info=True)
            return False

    def _read(self, attr: str) -> Any:
        try:
            return getattr(self._dev, attr)
        except Exception as exc:  # D-Bus / NotImplementedError
            logger.error("Reading %s failed", attr, exc_info=True)
            raise MouseError(f"Could not read {attr}: {exc}") from exc

    def _write(self, attr: str, value: Any) -> None:
        try:
            setattr(self._dev, attr, value)
        except Exception as exc:  # D-Bus / NotImplementedError / ValueError
            logger.error("Setting %s to %r failed", attr, value, exc_info=True)
            raise MouseError(f"Could not set {attr}: {exc}") from exc

    # --- DPI -------------------------------------------------------------

    def supports_dpi(self) -> bool:
        """True if the device has adjustable DPI."""
        return self._has(DPI_CAPABILITY)

    def max_dpi(self) -> int:
        """Maximum DPI supported by the sensor."""
        return int(self._read("max_dpi"))

    def available_dpi(self) -> list[int]:
        """Fixed DPI values, or an empty list when any value is allowed."""
        if not self._has(AVAILABLE_DPI_CAPABILITY):
            return []
        return sorted(int(value) for value in self._read("available_dpi") or [])

    def get_dpi(self) -> tuple[int, int]:
        """Current (x, y) DPI."""
        dpi_x, dpi_y = self._read("dpi")
        return int(dpi_x), int(dpi_y)

    def _fit_dpi(self, value: int, max_dpi: int, choices: list[int]) -> int:
        clamped = max(MIN_DPI, min(max_dpi, int(value)))
        if not choices:
            return clamped
        return min(choices, key=lambda choice: (abs(choice - clamped), choice))

    def set_dpi(self, x: int, y: int | None = None) -> tuple[int, int]:
        """Set DPI; ``y`` defaults to ``x``. Returns the (x, y) actually applied.

        Values are clamped to MIN_DPI..max_dpi and snapped to the nearest
        available DPI when the device has a fixed list. Such devices only
        accept an X value, so Y is sent as 0 (as openrazer requires).
        """
        if y is None:
            y = x
        for value in (x, y):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"DPI must be an integer, got {value!r}")
        max_dpi = self.max_dpi()
        choices = self.available_dpi()
        applied_x = self._fit_dpi(x, max_dpi, choices)
        applied_y = 0 if choices else self._fit_dpi(y, max_dpi, choices)
        self._write("dpi", (applied_x, applied_y))
        return applied_x, applied_y

    # --- Polling rate ----------------------------------------------------

    def supports_poll_rate(self) -> bool:
        """True if the polling rate can be changed."""
        return self._has(POLL_RATE_CAPABILITY)

    def supported_poll_rates(self) -> list[int]:
        """Supported polling rates in Hz, falling back to FALLBACK_POLL_RATES."""
        if not self._has(SUPPORTED_POLL_RATES_CAPABILITY):
            return list(FALLBACK_POLL_RATES)
        rates = sorted(int(rate) for rate in self._read("supported_poll_rates") or [])
        return rates or list(FALLBACK_POLL_RATES)

    def get_poll_rate(self) -> int:
        """Current polling rate in Hz."""
        return int(self._read("poll_rate"))

    def set_poll_rate(self, rate: int) -> int:
        """Set the polling rate; raises ValueError if it is not supported."""
        supported = self.supported_poll_rates()
        if isinstance(rate, bool) or rate not in supported:
            raise ValueError(f"Poll rate {rate!r} not in supported rates {supported}")
        self._write("poll_rate", int(rate))
        return int(rate)
