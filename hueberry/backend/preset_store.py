# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Load and save the user's lighting presets in presets.json (XDG config dir).

Only user presets are stored; the built-in ones (:data:`presets.BUILTIN_PRESETS`)
always come from code, so a saved preset can never shadow them. Saves are
atomic and mode 0600; an unparseable file is moved aside to ``.bak`` rather
than overwritten (see :mod:`hueberry.config_files`).
"""

import logging
import re
from pathlib import Path
from typing import Iterable

from hueberry import config_files
from hueberry.backend import presets
from hueberry.backend.effects import Preset, PresetError

logger = logging.getLogger(__name__)

CONFIG_FILE_NAME = "presets.json"
SCHEMA_VERSION = 1
VERSION_KEY = "version"
PRESETS_KEY = "presets"
TEMP_PREFIX = ".presets-"
QUARANTINE_KIND = "preset file"
KEY_FALLBACK = "preset"
MAX_KEY_LENGTH = 64
SLUG_SEPARATOR = "-"
FIRST_SUFFIX = 2  # "name", then "name-2", "name-3", ...
NON_SLUG = re.compile(r"[^a-z0-9]+")


def config_path() -> Path:
    """``$XDG_CONFIG_HOME/hueberry/presets.json`` (default ``~/.config``)."""
    return config_files.config_dir() / CONFIG_FILE_NAME


def builtin_keys() -> frozenset[str]:
    """Keys reserved by the built-in presets."""
    return frozenset(preset.key for preset in presets.BUILTIN_PRESETS)


def _keep(preset: Preset, seen: set[str]) -> bool:
    """False (with a warning) for a preset clashing with a built-in or an earlier one."""
    if preset.key in builtin_keys():
        logger.warning("Skipping saved preset %r: the key belongs to a built-in", preset.key)
        return False
    if preset.key in seen:
        logger.warning("Skipping duplicate saved preset %r", preset.key)
        return False
    seen.add(preset.key)
    return True


def _parse(raw: bytes) -> list[Preset]:
    """Parse and validate file contents; any problem raises ValueError."""
    data = config_files.parse_json(raw)
    if not isinstance(data, dict) or data.get(VERSION_KEY) != SCHEMA_VERSION:
        raise PresetError(f"unsupported schema version (expected {SCHEMA_VERSION})")
    entries = data.get(PRESETS_KEY)
    if not isinstance(entries, list):
        raise PresetError(f"{PRESETS_KEY!r} must be a list")
    seen: set[str] = set()
    loaded = [Preset.from_dict(entry) for entry in entries]
    return [preset for preset in loaded if _keep(preset, seen)]


def load(path: Path | None = None) -> tuple[list[Preset], str | None]:
    """Return ``(user_presets, error)``; a missing file is no presets, not an error."""
    path = path if path is not None else config_path()
    return config_files.load_file(path, QUARANTINE_KIND, _parse, list)


def _check_saveable(user_presets: list[Preset]) -> None:
    """Raise PresetError for invalid, built-in or duplicate presets."""
    seen: set[str] = set()
    for preset in user_presets:
        preset.validate()
        if preset.builtin or preset.key in builtin_keys():
            raise PresetError(f"built-in preset {preset.key!r} cannot be saved")
        if preset.key in seen:
            raise PresetError(f"duplicate preset key {preset.key!r}")
        seen.add(preset.key)


def save(user_presets: Iterable[Preset], path: Path | None = None) -> None:
    """Validate, then atomically replace presets.json (mode 0600).

    Raises PresetError for invalid, built-in or duplicate presets and OSError
    for I/O failures; on any failure the previous file is untouched.
    """
    user_presets = list(user_presets)
    _check_saveable(user_presets)
    path = path if path is not None else config_path()
    data = {VERSION_KEY: SCHEMA_VERSION, PRESETS_KEY: [p.to_dict() for p in user_presets]}
    config_files.atomic_write(path, config_files.dump_json(data), temp_prefix=TEMP_PREFIX)
    logger.info("Saved %d presets to %s", len(user_presets), path)


def all_presets(user_presets: Iterable[Preset]) -> list[Preset]:
    """Built-in presets first, then the user's."""
    return [*presets.BUILTIN_PRESETS, *user_presets]


def find_preset(key: str, candidates: Iterable[Preset]) -> Preset | None:
    """The preset with ``key`` among ``candidates``, or None."""
    return next((preset for preset in candidates if preset.key == key), None)


def unique_key(label: str, taken: Iterable[str]) -> str:
    """A valid preset key derived from ``label``, unused by ``taken`` and built-ins."""
    used = set(taken) | builtin_keys()
    base = NON_SLUG.sub(SLUG_SEPARATOR, label.lower()).strip(SLUG_SEPARATOR) or KEY_FALLBACK
    key = base[:MAX_KEY_LENGTH]
    suffix = FIRST_SUFFIX
    while key in used:
        tail = f"{SLUG_SEPARATOR}{suffix}"
        key = base[:MAX_KEY_LENGTH - len(tail)] + tail
        suffix += 1
    return key
