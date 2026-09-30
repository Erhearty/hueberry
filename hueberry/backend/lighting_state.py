# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""A thread-safe registry of lighting claims.

When a device is given other lighting (a hardware effect from the Lighting
page), :meth:`LightingState.claim` tells every claim listener - such as the
advanced per-key runtime - so it lets go of that device. Listeners are called
outside the lock; an exception from one is logged and never blocks the
lighting change or the other listeners.

Nothing here imports openrazer or Qt.
"""

import logging
import threading
from typing import Callable, Iterable

__all__ = ["ClaimListener", "LightingState", "shared_lighting_state"]

logger = logging.getLogger(__name__)

SERIAL_SEPARATOR = ", "

#: Called with the serials of devices taken over by other lighting.
ClaimListener = Callable[[tuple[str, ...]], None]


class LightingState:
    """Tells claim listeners which devices other lighting took."""

    def __init__(self) -> None:
        self._lock = threading.Lock()  # guards the listener list
        self._claim_listeners: list[ClaimListener] = []

    def add_claim_listener(self, callback: ClaimListener) -> None:
        """Call ``callback(serials)`` whenever devices are claimed for other lighting."""
        with self._lock:
            self._claim_listeners.append(callback)

    def claim(self, serials: Iterable[str]) -> None:
        """Tell listeners ``serials`` now show other lighting; their errors are logged."""
        claimed = tuple(serials)
        with self._lock:
            listeners = list(self._claim_listeners)
        for listener in listeners:
            try:
                listener(claimed)
            except Exception:  # a listener never blocks the lighting change
                logger.exception("Lighting claim listener failed for %s",
                                 SERIAL_SEPARATOR.join(claimed))


_shared: LightingState | None = None
_shared_lock = threading.Lock()


def shared_lighting_state() -> LightingState:
    """The process-wide :class:`LightingState`, created on first use."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = LightingState()
        return _shared
