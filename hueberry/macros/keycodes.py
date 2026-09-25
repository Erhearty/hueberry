# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Key/button names (evdev ``KEY_*`` / ``BTN_*``) and recording conversion.

Macros store key names rather than numeric codes so macros.json stays
readable and stable across kernels. ``evdev.ecodes`` is imported lazily: the
GUI may run without python-evdev, in which case names are checked by shape
only and the engine (which requires evdev) does the authoritative check.
"""

import logging
import re
from typing import Any, Iterable

from hueberry.macros import model

logger = logging.getLogger(__name__)

KEY_PREFIX = "KEY_"
BTN_PREFIX = "BTN_"
CODE_PREFIXES = (KEY_PREFIX, BTN_PREFIX)
EXCLUDED_SUFFIXES = ("_MAX", "_CNT")
EXCLUDED_NAMES = frozenset({"KEY_RESERVED"})
CODE_NAME_PATTERN = re.compile(r"^(KEY|BTN)_[A-Z0-9_]+$")
BUTTON_LABEL = "Button "
VALUE_RELEASE = 0
VALUE_PRESS = 1
VALUE_REPEAT = 2
MS_PER_S = 1000
DEFAULT_MIN_GAP_MS = 5


def _ecodes() -> Any:
    """``evdev.ecodes``, or None when python-evdev is not installed."""
    try:
        from evdev import ecodes  # lazy: optional dependency
    except ImportError:
        return None
    return ecodes


def _is_key_name(name: Any) -> bool:
    return (
        isinstance(name, str)
        and name.startswith(CODE_PREFIXES)
        and name not in EXCLUDED_NAMES
        and not name.endswith(EXCLUDED_SUFFIXES)
    )


def is_valid_code(name: Any) -> bool:
    """True for a real ``KEY_*``/``BTN_*`` name (shape-only without evdev)."""
    if not _is_key_name(name):
        return False
    ecodes = _ecodes()
    if ecodes is None:
        return bool(CODE_NAME_PATTERN.match(name))
    return name in ecodes.ecodes


def code_for(name: str) -> int | None:
    """Numeric evdev code for a key name, or None (unknown or no evdev)."""
    ecodes = _ecodes()
    if ecodes is None or not _is_key_name(name):
        return None
    return ecodes.ecodes.get(name)


def name_for(code: int) -> str | None:
    """Canonical key name for a numeric EV_KEY code (first alias), or None."""
    ecodes = _ecodes()
    if ecodes is None:
        return None
    for table in (ecodes.BTN, ecodes.KEY):
        names = table.get(code)
        if names:
            return names if isinstance(names, str) else names[0]
    return None


def display_name(name: str) -> str:
    """Readable label, e.g. ``KEY_LEFTCTRL`` -> ``Leftctrl``, ``BTN_SIDE`` -> ``Button Side``."""
    for prefix in CODE_PREFIXES:
        if name.startswith(prefix):
            words = name[len(prefix):].replace("_", " ").title()
            return BUTTON_LABEL + words if prefix == BTN_PREFIX else words
    return name


def all_key_names() -> list[str]:
    """Every bindable ``KEY_*``/``BTN_*`` name, sorted ([] without evdev)."""
    ecodes = _ecodes()
    if ecodes is None:
        return []
    return sorted(name for name in ecodes.ecodes if _is_key_name(name))


def _gap_step(previous_t: float | None, t: float, min_gap_ms: int) -> Any:
    """A DelayStep for the gap since the previous event, or None if too short."""
    if previous_t is None:
        return None
    gap_ms = round((t - previous_t) * MS_PER_S)
    if gap_ms < min_gap_ms:
        return None
    return model.DelayStep(min(gap_ms, model.MAX_DELAY_MS))


def events_to_steps(recorded: Iterable, min_gap_ms: int = DEFAULT_MIN_GAP_MS) -> list:
    """Turn recorded ``(code, value, t)`` key events into press/release/delay steps.

    Gaps shorter than ``min_gap_ms`` are dropped (they are scheduling noise,
    not intent); longer ones are clamped to MAX_DELAY_MS. Repeats and unknown
    codes are skipped, and the result is capped at MAX_STEPS.
    """
    steps: list = []
    previous_t = None
    for code, value, t in recorded:
        if value not in (VALUE_PRESS, VALUE_RELEASE) or not is_valid_code(code):
            continue
        delay = _gap_step(previous_t, t, min_gap_ms)
        if delay is not None:
            steps.append(delay)
        action = model.ACTION_PRESS if value == VALUE_PRESS else model.ACTION_RELEASE
        steps.append(model.KeyStep(code, action))
        previous_t = t
    return steps[:model.MAX_STEPS]
