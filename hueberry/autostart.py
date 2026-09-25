# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
""""Start Hueberry at login" via an XDG autostart entry.

The entry lives at ``$XDG_CONFIG_HOME/autostart/hueberry.desktop`` (default
``~/.config``) and starts Hueberry with ``--background``. It carries a marker
key so we only ever delete a file we wrote ourselves.
"""

import contextlib
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

CONFIG_HOME_FALLBACK = ".config"
AUTOSTART_DIR_NAME = "autostart"
DESKTOP_FILE_NAME = "hueberry.desktop"
SCRIPT_NAME = "hueberry"
BACKGROUND_FLAG = "--background"
MARKER_KEY = "X-Hueberry-Autostart"
MARKER_LINE = f"{MARKER_KEY}=true"
ENCODING = "utf-8"
TEMP_PREFIX = ".hueberry-"
TEMP_SUFFIX = ".tmp"
# Characters that force quoting of an Exec argument (Desktop Entry spec).
RESERVED_CHARS = frozenset(" \t\n\"'\\><~|&;$*?#()`")
ESCAPED_IN_QUOTES = ('\\', '"', "`", "$")
ENTRY_TEMPLATE = """[Desktop Entry]
Type=Application
Name=Hueberry
Comment=Razer device settings and macros (tray)
Exec={exec_line}
Terminal=false
X-GNOME-Autostart-enabled=true
{marker}
"""


class AutostartError(OSError):
    """The autostart entry could not be written or removed."""


def autostart_path() -> Path:
    """``$XDG_CONFIG_HOME/autostart/hueberry.desktop`` (default ``~/.config``)."""
    config_home = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / CONFIG_HOME_FALLBACK)
    return Path(config_home) / AUTOSTART_DIR_NAME / DESKTOP_FILE_NAME


def quote_arg(arg: str) -> str:
    """Quote one Exec argument per the Desktop Entry spec (``%`` is doubled)."""
    arg = arg.replace("%", "%%")
    if not any(char in RESERVED_CHARS for char in arg):
        return arg
    for char in ESCAPED_IN_QUOTES:
        arg = arg.replace(char, "\\" + char)
    return f'"{arg}"'


def exec_line(which: Callable[[str], str | None] = shutil.which, python: str = sys.executable) -> str:
    """The installed ``hueberry`` script if found, else ``python -m hueberry``."""
    script = which(SCRIPT_NAME)
    argv = [script] if script else [python, "-m", SCRIPT_NAME]
    return " ".join(quote_arg(arg) for arg in [*argv, BACKGROUND_FLAG])


def _is_ours(path: Path) -> bool:
    try:
        lines = path.read_text(encoding=ENCODING).splitlines()
    except (OSError, UnicodeDecodeError):
        return False
    return MARKER_LINE in (line.strip() for line in lines)


def is_enabled(path: Path | None = None) -> bool:
    """True when an autostart entry named hueberry.desktop exists."""
    return (path if path is not None else autostart_path()).is_file()


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=TEMP_PREFIX, suffix=TEMP_SUFFIX)
    try:
        with os.fdopen(fd, "w", encoding=ENCODING) as handle:
            handle.write(text)
        os.replace(temp_name, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temp_name)
        raise


def enable(path: Path | None = None, which: Callable[[str], str | None] = shutil.which,
           python: str = sys.executable) -> None:
    """Write the entry; refuses to overwrite a hueberry.desktop we did not write."""
    path = path if path is not None else autostart_path()
    if path.exists() and not _is_ours(path):
        raise AutostartError(f"{path} was not created by Hueberry; not overwriting it")
    text = ENTRY_TEMPLATE.format(exec_line=exec_line(which, python), marker=MARKER_LINE)
    try:
        _write_atomic(path, text)
    except OSError as exc:
        raise AutostartError(f"Cannot write {path}: {exc}") from exc
    logger.info("Autostart enabled: %s", path)


def disable(path: Path | None = None) -> None:
    """Remove our entry; a missing file is fine, a foreign one is refused."""
    path = path if path is not None else autostart_path()
    if not path.exists():
        return
    if not _is_ours(path):
        raise AutostartError(f"{path} was not created by Hueberry; not deleting it")
    try:
        path.unlink()
    except OSError as exc:
        raise AutostartError(f"Cannot remove {path}: {exc}") from exc
    logger.info("Autostart disabled: %s", path)


def set_autostart(enabled: bool) -> None:
    """Enable or disable autostart; raises AutostartError on failure."""
    if enabled:
        enable()
    else:
        disable()
