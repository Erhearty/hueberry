# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Worker jobs behind the Presets page's Apply, Stop and Save buttons.

The jobs run inside ``worker.run_async`` (off the UI thread) and go through
``lighting_state.shared_lighting_state()``, looked up at call time so tests
can patch it; whatever is applied here therefore comes back after a restart.
Any exception (including an ``OSError`` saving the lighting state) propagates
to the job's error callback, which the page shows on its status line.

Deleting a preset stays in memory until *Save*: :func:`save_presets` forgets
the assignments of the deleted keys only once presets.json is written, so an
unsaved delete never loses them.
"""

import logging
from typing import Any, Iterable

from hueberry.backend import lighting_state, preset_store
from hueberry.backend.effects import Preset

logger = logging.getLogger(__name__)

UNSAVED_NOTE = " (unsaved preset: it will not be restored after a restart until it is saved)"
FORGET_FAILED_TEXT = "Presets saved, but deleted presets were not stopped: {error}"


def apply_single(devs: Iterable[Any], preset: Preset) -> int:
    """Start ``preset`` on each device in its own run; the number started."""
    state = lighting_state.shared_lighting_state()
    return sum(1 for dev in devs if state.apply_single(dev, preset))


def apply_group(devs: Iterable[Any], preset: Preset) -> int:
    """Start ``preset`` on all devices as one synced group; the number started."""
    return len(lighting_state.shared_lighting_state().apply_group(devs, preset))


def stop(serials: Iterable[str]) -> int:
    """Stop and forget the preset on each of ``serials``; the number stopped."""
    state = lighting_state.shared_lighting_state()
    return sum(1 for serial in serials if state.stop_device(serial))


def save_presets(user: list[Preset], deleted: Iterable[str]) -> str | None:
    """Write presets.json, then forget the assignments of ``deleted`` keys.

    Raises like :func:`preset_store.save`; a failure to forget happens after
    the presets were saved, so it is returned as a message instead.
    """
    preset_store.save(user)
    try:
        for key in sorted(deleted):
            lighting_state.shared_lighting_state().forget_preset(key)
    except Exception as exc:  # the presets are saved either way
        logger.exception("Forgetting the lighting of deleted presets failed")
        return str(exc)
    return None


def is_unsaved(key: str, saved_keys: set[str]) -> bool:
    """True when ``key`` is neither a built-in nor in presets.json."""
    return key not in saved_keys and key not in preset_store.builtin_keys()


def unsaved_note(key: str, saved_keys: set[str]) -> str:
    """:data:`UNSAVED_NOTE` for an unsaved preset ``key``, else an empty string."""
    return UNSAVED_NOTE if is_unsaved(key, saved_keys) else ""
