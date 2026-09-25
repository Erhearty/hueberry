# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Small persistent GUI settings in ``$XDG_CONFIG_HOME/hueberry/settings.json``.

Unknown keys (e.g. written by a newer Hueberry) are kept on save; a value of
the wrong type or an unreadable file falls back to the defaults.
"""

import contextlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CONFIG_HOME_FALLBACK = ".config"
CONFIG_DIR_NAME = "hueberry"
SETTINGS_FILE_NAME = "settings.json"
ENCODING = "utf-8"
JSON_INDENT = 2
DIR_MODE = 0o700
TEMP_PREFIX = ".settings-"
TEMP_SUFFIX = ".tmp"
CLOSE_TO_TRAY = "close_to_tray"
DEFAULTS: dict[str, Any] = {CLOSE_TO_TRAY: True}


def settings_path() -> Path:
    """``$XDG_CONFIG_HOME/hueberry/settings.json`` (default ``~/.config``)."""
    config_home = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / CONFIG_HOME_FALLBACK)
    return Path(config_home) / CONFIG_DIR_NAME / SETTINGS_FILE_NAME


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding=ENCODING))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:  # unreadable or corrupt: use defaults
        logger.warning("Ignoring unreadable settings file %s: %s", path, exc)
        return {}
    if not isinstance(data, dict):
        logger.warning("Ignoring settings file %s: not a JSON object", path)
        return {}
    return data


class Settings:
    """Key/value settings with typed defaults; ``set`` saves immediately."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else settings_path()
        self._data = _read(self.path)

    def get(self, key: str) -> Any:
        """The stored value, or the default when missing or of the wrong type."""
        default = DEFAULTS[key]
        value = self._data.get(key, default)
        return value if type(value) is type(default) else default

    def set(self, key: str, value: Any) -> None:
        """Store and save ``value``; raises OSError when the file cannot be written."""
        self._data[key] = value
        self.save()

    @property
    def close_to_tray(self) -> bool:
        """Keep running in the background when the window is closed."""
        return self.get(CLOSE_TO_TRAY)

    def save(self) -> None:
        """Atomically write every key, including unknown ones."""
        self.path.parent.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
        payload = json.dumps(self._data, indent=JSON_INDENT, sort_keys=True)
        fd, temp_name = tempfile.mkstemp(dir=self.path.parent, prefix=TEMP_PREFIX, suffix=TEMP_SUFFIX)
        try:
            with os.fdopen(fd, "w", encoding=ENCODING) as handle:
                handle.write(payload)
            os.replace(temp_name, self.path)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temp_name)
            raise
