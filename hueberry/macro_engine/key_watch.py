# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Watches key-downs on devices chosen by name, for the UI to poll.

The UI names devices (case-insensitive substrings of the evdev name); the
engine keeps their nodes open without grabbing and records every key-down
into a bounded ring buffer. Each event gets a monotonically increasing
sequence number, so a poller passes back the ``next`` cursor it was given
and never sees an event twice; events that fell out of the buffer are lost.
"""

from collections import deque
from typing import Any, Callable, Iterable

from hueberry.macro_engine.nodes import attach_missing
from hueberry.macros import keycodes

MAX_KEY_EVENTS = 512
KEY_DOWN = keycodes.VALUE_PRESS
FIRST_SEQ = 0
ARG_NAMES = "names"
ARG_SINCE = "since"


class CommandError(ValueError):
    """A well-formed request that cannot be carried out (sent back as an error)."""


class KeyWatch:
    """Name filter plus a ring buffer of ``(code, seq, t_ms)`` key-downs."""

    def __init__(self, max_events: int = MAX_KEY_EVENTS) -> None:
        self._names: tuple[str, ...] = ()
        self._events: deque[tuple[int, int, int]] = deque(maxlen=max_events)
        self._next_seq = FIRST_SEQ
        self._ev_key: int | None = None

    def set_names(self, names: Iterable[str]) -> None:
        """Replace the watched names; empty strings are ignored (they would match everything)."""
        self._names = tuple(name.casefold() for name in names if name)

    def matches(self, entry_name: str) -> bool:
        """True when any watched name is a case-insensitive substring of ``entry_name``."""
        folded = entry_name.casefold()
        return any(name in folded for name in self._names)

    def wanted(self, entries: Iterable[Any]) -> list:
        """The entries (anything with a ``name``) whose name matches."""
        return [entry for entry in entries if self.matches(entry.name)]

    def record(self, code: int, value: int, t: float) -> None:
        """Keep a key-down (``value == KEY_DOWN``) at ``t`` seconds; anything else is ignored."""
        if value != KEY_DOWN:
            return
        self._events.append((int(code), self._next_seq, round(t * keycodes.MS_PER_S)))
        self._next_seq += 1

    def handle(self, event: Any) -> None:
        """Record an evdev event if it is an EV_KEY key-down."""
        if self._ev_key is None:
            from evdev import ecodes  # lazy: optional dependency

            self._ev_key = ecodes.EV_KEY
        if event.type == self._ev_key:
            self.record(event.code, event.value, event.timestamp())

    def events_since(self, since: int) -> tuple[list[list[int]], int]:
        """``([[code, seq, t_ms], ...], next_seq)`` for the buffered events with ``seq >= since``."""
        events = [[code, seq, t_ms] for code, seq, t_ms in self._events if seq >= since]
        return events, self._next_seq


def parse_names(args: dict) -> list[str] | None:
    """``args['names']`` when it is a list of strings, else None."""
    names = args.get(ARG_NAMES)
    if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
        return None
    return names


def parse_since(args: dict) -> int | None:
    """``args['since']`` when it is a non-negative int (not a bool), else None."""
    since = args.get(ARG_SINCE)
    if isinstance(since, bool) or not isinstance(since, int) or since < FIRST_SEQ:
        return None
    return since


def apply_watch(
    key_watch: KeyWatch,
    args: dict,
    discover: Callable[[], Iterable[Any]],
    handles: dict,
    attach: Callable[[Any], Any],
    release: Callable[[str], None],
) -> dict:
    """The ``key_watch`` op: set the names, open matching nodes, release unused ones."""
    names = parse_names(args)
    if names is None:
        raise CommandError("key_watch needs 'names' as a list of strings")
    key_watch.set_names(names)
    if names:
        attach_missing(key_watch.wanted(discover()), handles, attach)
    for path in list(handles):
        release(path)
    watched = sorted(path for path, handle in handles.items() if key_watch.matches(handle.name))
    return {"names": names, "nodes": watched}


def key_events_reply(key_watch: KeyWatch, args: dict) -> dict:
    """The ``key_events`` op: key-downs with ``seq >= since`` plus the ``next`` cursor."""
    since = parse_since(args)
    if since is None:
        raise CommandError("key_events needs a non-negative integer 'since'")
    events, next_seq = key_watch.events_since(since)
    return {"events": events, "next": next_seq}
