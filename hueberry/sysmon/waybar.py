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
from hueberry.sysmon.config import ALIGN_CENTER, ALIGN_END, ALIGN_START, SysmonConfig

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
MARGIN_SIDES = ("top", "right", "bottom", "left")
SIZE_FIELDS = ("width", "height")
ALIGNMENT_MODULES_KEY = {
    ALIGN_START: "modules-left",
    ALIGN_CENTER: "modules-center",
    ALIGN_END: "modules-right",
}


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
    bar: dict[str, Any] = {
        "name": BAR_NAME,
        "layer": BAR_LAYER,
        "exclusive": False,
        "passthrough": True,
        "position": cfg.edge,
        ALIGNMENT_MODULES_KEY[cfg.alignment]: [MODULE_NAME],
    }
    for side in MARGIN_SIDES:
        bar[f"margin-{side}"] = getattr(cfg, f"margin_{side}")
    for name in SIZE_FIELDS:
        if getattr(cfg, name):
            bar[name] = getattr(cfg, name)
    bar[MODULE_NAME] = _module_config(config_path, python)
    return bar


def write_files(cfg: SysmonConfig, config_path: Path,
                out_dir: Path | None = None) -> tuple[Path, Path]:
    """Write ``config.json`` and, if missing, the bundled ``style.css``.

    Returns ``(waybar_config_path, style_path)``. The config is always
    replaced atomically; an existing style sheet is left as the user edited it.
    Raises OSError on I/O failures.
    """
    out_dir = out_dir if out_dir is not None else default_out_dir()
    out_dir.mkdir(mode=config_files.DIR_MODE, parents=True, exist_ok=True)
    waybar_path = out_dir / WAYBAR_CONFIG_NAME
    payload = config_files.dump_json(build_waybar_config(cfg, config_path))
    config_files.atomic_write(waybar_path, payload, temp_prefix=TEMP_PREFIX)
    style_path = out_dir / STYLE_NAME
    if not style_path.exists():
        style = files(DATA_PACKAGE).joinpath(BUNDLED_STYLE).read_bytes()
        config_files.atomic_write(style_path, style, temp_prefix=TEMP_PREFIX)
        logger.info("Installed default sysmon style at %s", style_path)
    return waybar_path, style_path
