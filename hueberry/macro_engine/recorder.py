# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Records key/button events of one device for turning into a macro.

Only EV_KEY presses and releases are kept (auto-repeat is noise for a
macro); the event count is capped so a forgotten recording cannot grow
without bound, and the cap keeps the converted macro within MAX_STEPS.
"""

import logging
from typing import Any

from hueberry.macros import keycodes
from hueberry.macros.model import MAX_STEPS

logger = logging.getLogger(__name__)

MAX_RECORDED_EVENTS = MAX_STEPS // 2  # each event may add a delay step as well
TIMESTAMP_DIGITS = 6


class Recorder:
    """Collects ``(code name, value, seconds since first event)`` for ``identity``."""

    def __init__(self, identity: str, max_events: int = MAX_RECORDED_EVENTS) -> None:
        from evdev import ecodes  # lazy: optional dependency

        self.identity = identity
        self._ev_key = ecodes.EV_KEY
        self._max_events = max_events
        self._events: list[tuple[str, int, float]] = []
        self._origin: float | None = None
        self.truncated = False

    @property
    def count(self) -> int:
        """Events recorded so far."""
        return len(self._events)

    def handle(self, event: Any) -> None:
        """Keep EV_KEY press/release events with a known name, up to the cap."""
        if event.type != self._ev_key or event.value == keycodes.VALUE_REPEAT:
            return
        name = keycodes.name_for(event.code)
        if name is None:
            return
        if len(self._events) >= self._max_events:
            if not self.truncated:
                logger.info("Recording for %s reached %d events", self.identity, self._max_events)
            self.truncated = True
            return
        stamp = event.timestamp()
        if self._origin is None:
            self._origin = stamp
        self._events.append((name, int(event.value), round(stamp - self._origin, TIMESTAMP_DIGITS)))

    def stop(self) -> list[list]:
        """The recording as JSON-safe ``[[code, value, t], ...]``."""
        return [[name, value, stamp] for name, value, stamp in self._events]
