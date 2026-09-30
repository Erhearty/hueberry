# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Generate the Waybar configuration that renders the system monitor overlay.

Waybar runs the metrics collector as a ``custom/sysmon`` module and draws its
JSON output as a transparent, click-through overlay bar. This module must stay
free of PyQt imports; ``build_waybar_config`` is pure, ``write_files`` puts the
result (plus a user-editable style sheet) on disk.
"""

import logging
import shlex
import sys
from importlib.resources import files
from pathlib import Path
from typing import Any

from hueberry import config_files
from hueberry.sysmon.config import (
    ALIGN_BOTTOM, ALIGN_CENTER, ALIGN_LEFT, ALIGN_RIGHT, ALIGN_TOP, SysmonConfig,
)

logger = logging.getLogger(__name__)

BAR_NAME = "hueberry-sysmon"
BAR_LAYER = "overlay"
MODULE_NAME = "custom/sysmon"
COLLECTOR_MODULE = "hueberry.sysmon.collector"
RESTART_INTERVAL_S = 5  # Waybar restarts the collector this long after it exits
OUT_DIR_NAME = "sysmon"
WAYBAR_CONFIG_NAME = "config.json"
STYLE_NAME = "style.css"
DATA_PACKAGE = "hueberry.data"
BUNDLED_STYLE = "sysmon/style.css"
TEMP_PREFIX = ".sysmon-waybar-"
# Earlier bundled style sheets, byte for byte: an installed copy still equal to
# one of these was never edited by the user and is upgraded to the current one.
LEGACY_BUNDLED_STYLES = (
    b"/* SPDX-License-Identifier: GPL-3.0-or-later */\n"
    b"/* SPDX-FileCopyrightText: 2025 Hueberry contributors */\n"
    b'* { font-family: "DejaVu Sans Mono"; font-size: 12px; }\n'
    b"window#waybar { background: rgba(0, 0, 0, 0.55); border-radius: 8px; }\n"
    b"#custom-sysmon { color: #ffffff; padding: 4px 12px; }\n",
)
MARGIN_SIDES = ("top", "right", "bottom", "left")
WIDTH_FIELD = "width"
HEIGHT_FIELD = "height"
# Waybar bar positions share their spelling with the config's alignments.
POSITION_TOP = ALIGN_TOP
POSITION_BOTTOM = ALIGN_BOTTOM
POSITION_LEFT = ALIGN_LEFT
POSITION_RIGHT = ALIGN_RIGHT
HORIZONTAL_POSITIONS = (POSITION_TOP, POSITION_BOTTOM)
MODULES_LEFT = "modules-left"
MODULES_CENTER = "modules-center"
MODULES_RIGHT = "modules-right"
ALIGN_X_MODULES_KEY = {
    ALIGN_LEFT: MODULES_LEFT,
    ALIGN_CENTER: MODULES_CENTER,
    ALIGN_RIGHT: MODULES_RIGHT,
}


def bar_position(cfg: SysmonConfig) -> tuple[str, str]:
    """``(position, modules_key)`` placing the overlay per ``cfg.align_x``/``align_y``.

    A top/bottom ``align_y`` makes a top/bottom bar with the module in the
    ``modules-*`` list picked by ``align_x``. A center ``align_y`` makes a
    left/right bar (per ``align_x``) with the module vertically centered.
    ``cfg`` must be valid (align_x and align_y are never both center).
    """
    if cfg.align_y in HORIZONTAL_POSITIONS:
        return cfg.align_y, ALIGN_X_MODULES_KEY[cfg.align_x]
    return cfg.align_x, MODULES_CENTER


def default_out_dir() -> Path:
    """``$XDG_CONFIG_HOME/hueberry/sysmon`` - where the Waybar files live."""
    return config_files.config_dir() / OUT_DIR_NAME


def _module_config(config_path: Path, python: str) -> dict[str, Any]:
    """The ``custom/sysmon`` module running the collector on ``config_path``."""
    command = [python, "-m", COLLECTOR_MODULE, "--config", str(config_path)]
    return {
        "exec": shlex.join(command),
        "return-type": "json",
        "format": "{}",
        "tooltip": False,
        "restart-interval": RESTART_INTERVAL_S,
    }


def build_waybar_config(cfg: SysmonConfig, config_path: Path,
                        python: str = sys.executable) -> dict[str, Any]:
    """Waybar bar config placing the overlay per ``cfg`` (pure, no I/O)."""
    position, key = bar_position(cfg)
    bar: dict[str, Any] = {
        "name": BAR_NAME,
        "layer": BAR_LAYER,
        "exclusive": False,
        "passthrough": True,
        "position": position,
        key: [MODULE_NAME],
    }
    for side in MARGIN_SIDES:
        bar[f"margin-{side}"] = getattr(cfg, f"margin_{side}")
    # Waybar centers a top/bottom bar with a fixed width, so only the
    # dimension across the bar is ever passed on.
    size = HEIGHT_FIELD if position in HORIZONTAL_POSITIONS else WIDTH_FIELD
    if getattr(cfg, size):
        bar[size] = getattr(cfg, size)
    bar[MODULE_NAME] = _module_config(config_path, python)
    return bar


def _install_style(style_path: Path) -> None:
    """Copy the bundled style sheet to ``style_path`` unless the user edited it.

    A missing file is installed; a file byte-identical to an earlier bundled
    version is upgraded; any other content is left untouched.
    Raises OSError on I/O failures.
    """
    if not style_path.exists():
        message = "Installed default sysmon style at %s"
    elif style_path.read_bytes() in LEGACY_BUNDLED_STYLES:
        message = "Upgraded default sysmon style at %s"
    else:
        return
    style = files(DATA_PACKAGE).joinpath(BUNDLED_STYLE).read_bytes()
    config_files.atomic_write(style_path, style, temp_prefix=TEMP_PREFIX)
    logger.info(message, style_path)


def write_files(cfg: SysmonConfig, config_path: Path,
                out_dir: Path | None = None) -> tuple[Path, Path]:
    """Write ``config.json`` and install or upgrade the bundled ``style.css``.

    Returns ``(waybar_config_path, style_path)``. The config is always
    replaced atomically; a missing or unedited earlier bundled style sheet is
    replaced with the current one, a user-edited one is left untouched.
    Raises OSError on I/O failures.
    """
    out_dir = out_dir if out_dir is not None else default_out_dir()
    out_dir.mkdir(mode=config_files.DIR_MODE, parents=True, exist_ok=True)
    waybar_path = out_dir / WAYBAR_CONFIG_NAME
    payload = config_files.dump_json(build_waybar_config(cfg, config_path))
    config_files.atomic_write(waybar_path, payload, temp_prefix=TEMP_PREFIX)
    style_path = out_dir / STYLE_NAME
    _install_style(style_path)
    return waybar_path, style_path
