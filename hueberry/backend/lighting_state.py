# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Remember which lighting preset each device shows, across restarts.

An :class:`Assignment` is one preset shown on one device on its own
(:data:`MODE_SINGLE`) or on an ordered synced group (:data:`MODE_GROUP`); a
device belongs to at most one assignment. They are kept in
``lighting_state.json`` in the XDG config directory as
``{"version": 1, "assignments": [...]}``, written atomically with mode 0600
through :mod:`hueberry.config_files`; an invalid file is moved aside to
``.bak`` and reported, a missing one means no assignments.

The file changes only on explicit actions: :meth:`LightingState.apply_single`,
:meth:`LightingState.apply_group`, :meth:`LightingState.stop_device`,
:meth:`LightingState.forget_preset`, and :meth:`LightingState.restore`
dropping an assignment whose preset no longer exists. Animator shutdown and a
device vanishing in :meth:`Animator.refresh` leave it untouched, so a device
gets its preset back when it returns.

Save errors: an ``OSError`` from writing the file is logged and re-raised
*after* the animator and the in-memory assignments were updated, so the
lighting change stands and the caller (the UI) shows the error.

Nothing here imports openrazer or Qt: device objects are passed in.
"""

import logging
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Iterable

from hueberry import config_files
from hueberry.backend import animator as animator_module
from hueberry.backend import preset_store
from hueberry.backend.animator import Animator, RunInfo, device_serial
from hueberry.backend.effects import Preset

__all__ = ["Assignment", "LightingState", "LightingStateError", "MODE_GROUP", "MODE_SINGLE",
           "config_path", "load", "save", "shared_lighting_state"]

logger = logging.getLogger(__name__)

CONFIG_FILE_NAME = "lighting_state.json"
SCHEMA_VERSION = 1
VERSION_KEY = "version"
ASSIGNMENTS_KEY = "assignments"
PRESET_KEY_FIELD = "preset_key"
MODE_FIELD = "mode"
SERIALS_FIELD = "serials"
MODE_SINGLE = "single"
MODE_GROUP = "group"
MODES = (MODE_SINGLE, MODE_GROUP)
SINGLE_SIZE = 1  # a single assignment holds exactly one serial
TEMP_PREFIX = ".lighting-state-"
QUARANTINE_KIND = "lighting state file"
SERIAL_SEPARATOR = ", "


class LightingStateError(ValueError):
    """An invalid lighting state file or assignment."""


def _check_serials(serials: Any, mode: str) -> tuple[str, ...]:
    """Validate a JSON serial list for ``mode``; raises LightingStateError."""
    if not isinstance(serials, list) or not serials:
        raise LightingStateError(f"{SERIALS_FIELD!r} must be a non-empty list")
    if not all(isinstance(serial, str) and serial for serial in serials):
        raise LightingStateError("every serial must be a non-empty string")
    if len(set(serials)) != len(serials):
        raise LightingStateError("duplicate serial in one assignment")
    if mode == MODE_SINGLE and len(serials) != SINGLE_SIZE:
        raise LightingStateError(f"a {MODE_SINGLE} assignment holds exactly one serial")
    return tuple(serials)


@dataclass(frozen=True)
class Assignment:
    """One preset on one device (single) or on an ordered synced group."""

    preset_key: str
    mode: str
    serials: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """The JSON form stored in the file."""
        return {PRESET_KEY_FIELD: self.preset_key, MODE_FIELD: self.mode,
                SERIALS_FIELD: list(self.serials)}

    @classmethod
    def from_dict(cls, entry: Any) -> "Assignment":
        """Validate and build an assignment; raises LightingStateError."""
        if not isinstance(entry, dict):
            raise LightingStateError("an assignment must be an object")
        key, mode = entry.get(PRESET_KEY_FIELD), entry.get(MODE_FIELD)
        if not isinstance(key, str) or not key:
            raise LightingStateError(f"{PRESET_KEY_FIELD!r} must be a non-empty string")
        if not isinstance(mode, str) or mode not in MODES:
            raise LightingStateError(f"unknown mode {mode!r}")
        return cls(key, mode, _check_serials(entry.get(SERIALS_FIELD), mode))

    def without(self, serials: set[str]) -> "Assignment | None":
        """This assignment minus ``serials``, or None when nothing is left."""
        remaining = tuple(serial for serial in self.serials if serial not in serials)
        return replace(self, serials=remaining) if remaining else None


def config_path() -> Path:
    """``$XDG_CONFIG_HOME/hueberry/lighting_state.json`` (default ``~/.config``)."""
    return config_files.config_dir() / CONFIG_FILE_NAME


def _parse(raw: bytes) -> list[Assignment]:
    """Parse and validate file contents; any problem raises ValueError."""
    data = config_files.parse_json(raw)
    if not isinstance(data, dict) or data.get(VERSION_KEY) != SCHEMA_VERSION:
        raise LightingStateError(f"unsupported schema version (expected {SCHEMA_VERSION})")
    entries = data.get(ASSIGNMENTS_KEY)
    if not isinstance(entries, list):
        raise LightingStateError(f"{ASSIGNMENTS_KEY!r} must be a list")
    assignments = [Assignment.from_dict(entry) for entry in entries]
    serials = [serial for assignment in assignments for serial in assignment.serials]
    if len(set(serials)) != len(serials):
        raise LightingStateError("a device is in more than one assignment")
    return assignments


def load(path: Path | None = None) -> tuple[list[Assignment], str | None]:
    """Return ``(assignments, error)``; a missing file is no assignments, not an error."""
    path = path if path is not None else config_path()
    return config_files.load_file(path, QUARANTINE_KIND, _parse, list)


def save(assignments: Iterable[Assignment], path: Path | None = None) -> None:
    """Atomically replace the file (mode 0600); raises OSError on I/O failures."""
    assignments = list(assignments)
    path = path if path is not None else config_path()
    data = {VERSION_KEY: SCHEMA_VERSION, ASSIGNMENTS_KEY: [a.to_dict() for a in assignments]}
    config_files.atomic_write(path, config_files.dump_json(data), temp_prefix=TEMP_PREFIX)
    logger.info("Saved %d lighting assignments to %s", len(assignments), path)


def _default_presets() -> tuple[list[Preset], str | None]:
    """Built-in presets, then the saved user presets; and the load error (or None).

    The error is sticky for the session (:func:`preset_store.session_error`):
    once presets.json was quarantined, later loads find no file, and restore
    must still not drop the assignments of the presets it held.
    """
    user, error = preset_store.load()
    return preset_store.all_presets(user), error or preset_store.session_error()


def _without(assignments: Iterable[Assignment], serials: set[str]) -> list[Assignment]:
    """``assignments`` minus ``serials``; assignments left empty are dropped."""
    remaining = (assignment.without(serials) for assignment in assignments)
    return [assignment for assignment in remaining if assignment is not None]


def _by_serial(devices: Iterable[Any]) -> dict[str, Any]:
    """Present devices keyed by serial (unreadable serials are skipped)."""
    present: dict[str, Any] = {}
    for dev in devices:
        serial = device_serial(dev)
        if serial is not None:
            present[serial] = dev
    return present


def _matches(run: RunInfo, assignment: Assignment, members: list[str]) -> bool:
    """True when ``run`` already shows ``assignment`` on exactly ``members``."""
    return (run.preset.key == assignment.preset_key and run.serials == tuple(members)
            and run.grouped == (assignment.mode == MODE_GROUP))


class LightingState:
    """The saved preset assignments, kept in step with an :class:`Animator`.

    :param animator: the animator that shows the presets.
    :param presets_provider: returns ``(presets, error)``: the presets restore
        may use and why they could not all be loaded, or None (default: the
        built-ins, then the saved user presets).
    :param path: the state file (default :func:`config_path`, read at use).
    """

    def __init__(self, animator: Animator,
                 presets_provider: Callable[[], tuple[list[Preset], str | None]] = (
                     _default_presets),
                 path: Path | None = None) -> None:
        self._animator = animator
        self._presets_provider = presets_provider
        self._path = path
        self._lock = threading.RLock()  # guards the assignments and file writes
        self._assignments: list[Assignment] | None = None  # loaded on first use
        self._load_error: str | None = None

    def assignments(self) -> list[Assignment]:
        """The current assignments (loaded from the file on first use)."""
        with self._lock:
            return list(self._loaded())

    def apply_single(self, dev: Any, preset: Preset) -> bool:
        """Show ``preset`` on ``dev`` alone and remember it; False if unsupported."""
        if not self._animator.start(dev, preset):
            return False
        serial = device_serial(dev)
        if serial is not None:
            self._assign(Assignment(preset.key, MODE_SINGLE, (serial,)))
        return True

    def apply_group(self, devs: Iterable[Any], preset: Preset) -> list[str]:
        """Show ``preset`` on ``devs`` as one synced group and remember its order."""
        serials = self._animator.start_group(devs, preset)
        if serials:
            self._assign(Assignment(preset.key, MODE_GROUP, tuple(serials)))
        return serials

    def stop_device(self, serial: str) -> bool:
        """Stop animating ``serial`` and forget its assignment; True if it was running."""
        stopped = self._animator.stop(serial)
        self._update(lambda current: _without(current, {serial}))
        return stopped

    def forget_preset(self, key: str) -> int:
        """Stop and forget every assignment of preset ``key``; the number dropped."""
        with self._lock:
            doomed = [a for a in self._loaded() if a.preset_key == key]
        for assignment in doomed:
            for serial in assignment.serials:
                self._animator.stop(serial)
        self._update(lambda current: [a for a in current if a.preset_key != key])
        logger.info("Forgot %d lighting assignments of preset %s", len(doomed), key)
        return len(doomed)

    def restore(self, devices: Iterable[Any]) -> str | None:
        """Show the saved presets on the present ``devices``; idempotent.

        Returns a file load error once (None otherwise). Absent devices stay
        in their assignments; assignments of unknown presets are dropped, but
        not while the presets could not be loaded. A preset running in the
        animator is known even before it is saved.
        """
        with self._lock:
            saved = list(self._loaded())
            error, self._load_error = self._load_error, None
        if not saved:
            return error
        present = _by_serial(devices)
        known, presets_error = self._known_presets()
        for assignment in saved:
            if assignment.preset_key in known:
                self._restore_one(assignment, known[assignment.preset_key], present)
        unknown = [a for a in saved if a.preset_key not in known]
        if unknown:
            self._drop_unknown(unknown, presets_error)
        return error

    # -- internals -------------------------------------------------------------

    def _known_presets(self) -> tuple[dict[str, Preset], str | None]:
        """The presets restore may use, by key, and the provider's load error.

        The presets of live runs count too (and win): the Presets page can
        apply a preset that is not saved yet, and restore must not drop it.
        """
        provided, error = self._presets_provider()
        known = {preset.key: preset for preset in provided}
        known.update((run.preset.key, run.preset) for run in self._animator.runs())
        return known, error

    def _loaded(self) -> list[Assignment]:
        """The assignments, loading the file first if needed (caller holds the lock)."""
        if self._assignments is None:
            self._assignments, self._load_error = load(self._path)
        return self._assignments

    def _assign(self, new: Assignment) -> None:
        """Record ``new``, taking its devices out of every other assignment."""
        self._update(lambda current: [*_without(current, set(new.serials)), new])

    def _update(self, change: Callable[[list[Assignment]], list[Assignment]]) -> None:
        """Apply ``change`` to the assignments and save when they changed."""
        with self._lock:
            current = self._loaded()
            updated = change(list(current))
            if updated == current:
                return
            self._assignments = updated
            try:
                save(updated, self._path)
            except OSError:
                logger.exception("Could not save the lighting state")
                raise

    def _restore_one(self, assignment: Assignment, preset: Preset,
                     present: dict[str, Any]) -> None:
        """Start ``assignment`` on its present members unless it already runs."""
        members = [serial for serial in assignment.serials if serial in present]
        if not members or any(_matches(run, assignment, members)
                              for run in self._animator.runs()):
            return
        devs = [present[serial] for serial in members]
        if assignment.mode == MODE_GROUP:
            self._animator.start_group(devs, preset)  # even alone: keeps group semantics
        else:
            self._animator.start(devs[0], preset)
        logger.info("Restored preset %s on %s (%s)", assignment.preset_key,
                    SERIAL_SEPARATOR.join(members), assignment.mode)

    def _drop_unknown(self, unknown: list[Assignment], presets_error: str | None) -> None:
        """Forget assignments whose preset no longer exists (one save).

        With a ``presets_error`` the presets may exist but could not be read:
        keep every assignment and leave the file alone.
        """
        if presets_error is not None:
            logger.warning("Keeping %d lighting assignments of unknown presets: %s",
                           len(unknown), presets_error)
            return
        for assignment in unknown:
            logger.warning("Dropping saved lighting of %s: preset %r no longer exists",
                           SERIAL_SEPARATOR.join(assignment.serials), assignment.preset_key)
        dropped = set(unknown)
        self._update(lambda current: [a for a in current if a not in dropped])


_shared: LightingState | None = None
_shared_lock = threading.Lock()


def shared_lighting_state() -> LightingState:
    """The process-wide :class:`LightingState` over the shared animator, created on first use."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = LightingState(animator_module.shared_animator())
        return _shared
