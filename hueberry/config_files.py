# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Shared helpers for Hueberry's JSON files under the XDG config directory.

Every config file is written atomically (temp file in the same directory,
fsync, rename) so a reader never sees a half written file, and a file that
cannot be parsed is moved aside to ``.bak`` instead of being overwritten, so
the user's data is never silently lost.
"""

import contextlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

CONFIG_HOME_ENV = "XDG_CONFIG_HOME"
CONFIG_HOME_FALLBACK = ".config"
CONFIG_DIR_NAME = "hueberry"
BACKUP_SUFFIX = ".bak"
DEFAULT_TEMP_PREFIX = ".hueberry-"
TEMP_SUFFIX = ".tmp"
FILE_MODE = 0o600
DIR_MODE = 0o700
ENCODING = "utf-8"
JSON_INDENT = 2
MAX_FILE_BYTES = 8 * 1024 * 1024

T = TypeVar("T")


def config_dir() -> Path:
    """``$XDG_CONFIG_HOME/hueberry`` (default ``~/.config/hueberry``)."""
    config_home = os.environ.get(CONFIG_HOME_ENV) or str(Path.home() / CONFIG_HOME_FALLBACK)
    return Path(config_home) / CONFIG_DIR_NAME


def atomic_write(path: Path, payload: bytes, temp_prefix: str = DEFAULT_TEMP_PREFIX,
                 mode: int = FILE_MODE, dir_mode: int = DIR_MODE) -> None:
    """Atomically replace ``path`` with ``payload`` (file mode ``mode``).

    Raises OSError on I/O failures; the previous file is then untouched and
    no temp file is left behind.
    """
    path.parent.mkdir(mode=dir_mode, parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=temp_prefix, suffix=TEMP_SUFFIX)
    try:
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), mode)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temp_name)
        raise


def quarantine(path: Path, reason: Exception, kind: str) -> str:
    """Move a corrupt ``kind`` file to ``<name>.bak`` and describe what happened."""
    backup = path.with_name(path.name + BACKUP_SUFFIX)
    try:
        os.replace(path, backup)
    except OSError as exc:
        logger.error("Corrupt %s %s could not be moved aside: %s", kind, path, exc)
        return f"{path} is invalid ({reason}) and could not be moved aside: {exc}"
    logger.warning("Corrupt %s %s moved to %s: %s", kind, path, backup, reason)
    return f"{path} was invalid ({reason}); it was moved to {backup}"


def dump_json(data: Any) -> bytes:
    """Serialise ``data`` as indented UTF-8 JSON."""
    return json.dumps(data, indent=JSON_INDENT, ensure_ascii=False).encode(ENCODING)


def parse_json(raw: bytes, max_bytes: int = MAX_FILE_BYTES) -> Any:
    """Decode JSON file contents; oversize, Unicode and JSON errors raise ValueError."""
    if len(raw) > max_bytes:
        raise ValueError(f"file larger than {max_bytes} bytes")
    return json.loads(raw.decode(ENCODING))


def load_file(path: Path, kind: str, parse: Callable[[bytes], T],
              default: Callable[[], T]) -> tuple[T, str | None]:
    """Return ``(value, error)`` for ``path`` parsed by ``parse``.

    A missing file is ``default()`` without an error; an unreadable one is
    ``default()`` with an error; one ``parse`` rejects with ValueError is
    quarantined to ``.bak`` and reported.
    """
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return default(), None
    except OSError as exc:
        logger.warning("Cannot read %s %s: %s", kind, path, exc)
        return default(), f"Cannot read {path}: {exc}"
    try:
        return parse(raw), None
    except ValueError as exc:  # JSON, Unicode and model errors are all ValueErrors
        return default(), quarantine(path, exc, kind)
