# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Load and save advanced (per-key) presets in advanced_presets.json (XDG config dir).

Mirrors :mod:`hueberry.backend.preset_store`: saves are atomic and mode 0600;
an unparseable file is moved aside to ``.bak`` rather than overwritten (see
:mod:`hueberry.config_files`).
"""

import logging
import re
from pathlib import Path
from typing import Iterable

from hueberry import config_files
from hueberry.backend.advanced_presets import AdvancedPreset
from hueberry.backend.effects import PresetError

__all__ = ["config_path", "find_preset", "load", "save", "unique_key"]

logger = logging.getLogger(__name__)

CONFIG_FILE_NAME = "advanced_presets.json"
SCHEMA_VERSION = 1
VERSION_KEY = "version"
PRESETS_KEY = "presets"
TEMP_PREFIX = ".advanced-presets-"
QUARANTINE_KIND = "advanced preset file"
KEY_FALLBACK = "effect"
MAX_KEY_LENGTH = 64
SLUG_SEPARATOR = "-"
FIRST_SUFFIX = 2  # "name", then "name-2", "name-3", ...
NON_SLUG = re.compile(r"[^a-z0-9]+")


def config_path() -> Path:
    """``$XDG_CONFIG_HOME/hueberry/advanced_presets.json`` (default ``~/.config``)."""
    return config_files.config_dir() / CONFIG_FILE_NAME


def _check_unique(presets: list[AdvancedPreset]) -> None:
    keys = [preset.key for preset in presets]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        raise PresetError(f"duplicate advanced preset key {duplicates[0]!r}")


def _parse(raw: bytes) -> list[AdvancedPreset]:
    """Parse and validate file contents; any problem raises ValueError."""
    data = config_files.parse_json(raw)
    if not isinstance(data, dict) or data.get(VERSION_KEY) != SCHEMA_VERSION:
        raise PresetError(f"unsupported schema version (expected {SCHEMA_VERSION})")
    entries = data.get(PRESETS_KEY)
    if not isinstance(entries, list):
        raise PresetError(f"{PRESETS_KEY!r} must be a list")
    presets = [AdvancedPreset.from_dict(entry) for entry in entries]
    _check_unique(presets)
    return presets


def load(path: Path | None = None) -> tuple[list[AdvancedPreset], str | None]:
    """Return ``(presets, error)``; a missing file is no presets, not an error."""
    path = path if path is not None else config_path()
    return config_files.load_file(path, QUARANTINE_KIND, _parse, list)


def save(presets: Iterable[AdvancedPreset], path: Path | None = None) -> None:
    """Validate, then atomically replace the file (mode 0600).

    Raises PresetError for invalid or duplicate presets and OSError for I/O
    failures; on any failure the previous file is untouched.
    """
    presets = list(presets)
    for preset in presets:
        preset.validate()
    _check_unique(presets)
    path = path if path is not None else config_path()
    data = {VERSION_KEY: SCHEMA_VERSION, PRESETS_KEY: [p.to_dict() for p in presets]}
    config_files.atomic_write(path, config_files.dump_json(data), temp_prefix=TEMP_PREFIX)
    logger.info("Saved %d advanced presets to %s", len(presets), path)


def find_preset(key: str, candidates: Iterable[AdvancedPreset]) -> AdvancedPreset | None:
    """The preset with ``key`` among ``candidates``, or None."""
    return next((preset for preset in candidates if preset.key == key), None)


def unique_key(label: str, taken: Iterable[str]) -> str:
    """A valid preset key derived from ``label``, unused by ``taken``."""
    used = set(taken)
    base = NON_SLUG.sub(SLUG_SEPARATOR, label.lower()).strip(SLUG_SEPARATOR) or KEY_FALLBACK
    key = base[:MAX_KEY_LENGTH]
    suffix = FIRST_SUFFIX
    while key in used:
        tail = f"{SLUG_SEPARATOR}{suffix}"
        key = base[:MAX_KEY_LENGTH - len(tail)] + tail
        suffix += 1
    return key
