# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Load and save macros.json under the XDG config directory.

The GUI writes and the engine reads this file, so saves are atomic (temp
file in the same directory, fsync, rename): the engine never sees a half
written file. A file that cannot be parsed is moved aside to ``.bak`` rather
than overwritten, so a user's macros are never silently lost.
"""

import json
import logging
import os
from pathlib import Path

from hueberry import config_files
from hueberry.macros.model import MacroConfig, ModelError

logger = logging.getLogger(__name__)

CONFIG_HOME_FALLBACK = ".config"
CONFIG_DIR_NAME = "hueberry"
CONFIG_FILE_NAME = "macros.json"
BACKUP_SUFFIX = ".bak"
TEMP_PREFIX = ".macros-"
TEMP_SUFFIX = ".tmp"
SCHEMA_VERSION = 1
VERSION_KEY = "version"
FILE_MODE = 0o600
DIR_MODE = 0o700
ENCODING = "utf-8"
JSON_INDENT = 2
MAX_FILE_BYTES = 8 * 1024 * 1024
QUARANTINE_KIND = "macro file"  # log wording: "Corrupt macro file ..."


def config_path() -> Path:
    """``$XDG_CONFIG_HOME/hueberry/macros.json`` (default ``~/.config``)."""
    config_home = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / CONFIG_HOME_FALLBACK)
    return Path(config_home) / CONFIG_DIR_NAME / CONFIG_FILE_NAME


def _parse(raw: bytes) -> MacroConfig:
    """Parse and fully validate file contents; any problem raises ValueError."""
    if len(raw) > MAX_FILE_BYTES:
        raise ModelError(f"file larger than {MAX_FILE_BYTES} bytes")
    data = json.loads(raw.decode(ENCODING))
    if not isinstance(data, dict) or data.get(VERSION_KEY) != SCHEMA_VERSION:
        raise ModelError(f"unsupported schema version (expected {SCHEMA_VERSION})")
    config = MacroConfig.from_dict(data)
    config.validate()
    return config


def _quarantine(path: Path, reason: Exception) -> str:
    """Move a corrupt file to ``<name>.bak`` and describe what happened."""
    return config_files.quarantine(path, reason, QUARANTINE_KIND)


def load(path: Path | None = None) -> tuple[MacroConfig, str | None]:
    """Return ``(config, error)``; a missing file is an empty config, not an error."""
    path = path if path is not None else config_path()
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return MacroConfig(), None
    except OSError as exc:
        logger.warning("Cannot read macro file %s: %s", path, exc)
        return MacroConfig(), f"Cannot read {path}: {exc}"
    try:
        return _parse(raw), None
    except ValueError as exc:  # JSON, Unicode and model errors are all ValueErrors
        return MacroConfig(), _quarantine(path, exc)


def _serialise(config: MacroConfig) -> bytes:
    data = {VERSION_KEY: SCHEMA_VERSION, **config.to_dict()}
    return json.dumps(data, indent=JSON_INDENT, ensure_ascii=False).encode(ENCODING)


def save(config: MacroConfig, path: Path | None = None) -> None:
    """Validate, then atomically replace the file (mode 0600).

    Raises ModelError for invalid configs and OSError for I/O failures; on
    any failure the previous file is untouched and no temp file is left.
    """
    config.validate()
    path = path if path is not None else config_path()
    payload = _serialise(config)
    config_files.atomic_write(path, payload, temp_prefix=TEMP_PREFIX, mode=FILE_MODE,
                              dir_mode=DIR_MODE)
    logger.info("Saved macros to %s", path)
