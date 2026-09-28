# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the Waybar config generated for the system monitor overlay."""

import json
import shlex
from importlib.resources import files

import pytest

from hueberry.sysmon import waybar
from hueberry.sysmon.config import (
    ALIGN_CENTER, ALIGN_END, ALIGN_START, EDGES, SysmonConfig,
)

PYTHON = "/usr/bin/python3"
CONFIG_PATH = "/tmp/sysmon.json"
MODULE_KEYS = ("modules-left", "modules-center", "modules-right")
OLD_MARGIN_TOP = 40
OLD_MARGIN_RIGHT = 20
OLD_WIDTH = 500
CUSTOM_HEIGHT = 120
USER_STYLE = b"/* user edited */\n"


@pytest.fixture(autouse=True)
def _xdg(tmp_path, monkeypatch):
    """Point XDG_CONFIG_HOME at a temp dir so defaults never touch $HOME."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


def _build(cfg=None, config_path=CONFIG_PATH):
    """Build a Waybar config with a fixed interpreter path."""
    return waybar.build_waybar_config(cfg or SysmonConfig(), config_path, python=PYTHON)


def test_defaults_reproduce_old_config():
    """The default config matches the previously hand-written Waybar config."""
    bar = _build()
    assert bar["name"] == "hueberry-sysmon"
    assert bar["layer"] == "overlay"
    assert bar["exclusive"] is False
    assert bar["passthrough"] is True
    assert bar["position"] == "top"
    assert bar["modules-right"] == ["custom/sysmon"]
    assert bar["margin-top"] == OLD_MARGIN_TOP
    assert bar["margin-right"] == OLD_MARGIN_RIGHT
    assert bar["margin-bottom"] == 0
    assert bar["margin-left"] == 0
    assert bar["width"] == OLD_WIDTH
    assert "height" not in bar


def test_module_config():
    """The custom module runs the collector and returns JSON."""
    module = _build()["custom/sysmon"]
    assert module["return-type"] == "json"
    assert module["format"] == "{}"
    assert module["tooltip"] is False
    assert module["restart-interval"] == waybar.RESTART_INTERVAL_S
    assert shlex.split(module["exec"]) == [
        PYTHON, "-m", "hueberry.sysmon.collector", "--config", CONFIG_PATH]


@pytest.mark.parametrize("edge", EDGES)
def test_edge_maps_to_position(edge):
    """Each edge becomes the Waybar position."""
    assert _build(SysmonConfig(edge=edge))["position"] == edge


@pytest.mark.parametrize("alignment, key", [
    (ALIGN_START, "modules-left"),
    (ALIGN_CENTER, "modules-center"),
    (ALIGN_END, "modules-right"),
])
def test_alignment_maps_to_exactly_one_module_list(alignment, key):
    """The module lands in exactly one modules-* list chosen by alignment."""
    bar = _build(SysmonConfig(alignment=alignment))
    assert bar[key] == ["custom/sysmon"]
    assert [name for name in MODULE_KEYS if name in bar] == [key]


def test_size_only_when_non_zero():
    """Zero width/height are omitted; non-zero values are passed through."""
    assert "width" not in _build(SysmonConfig(width=0))
    assert _build(SysmonConfig(height=CUSTOM_HEIGHT))["height"] == CUSTOM_HEIGHT


def test_exec_quotes_path_with_space(tmp_path):
    """A config path containing a space round-trips through shlex.split."""
    path = tmp_path / "my dir" / "sysmon.json"
    command = shlex.split(_build(config_path=path)["custom/sysmon"]["exec"])
    assert command[-2:] == ["--config", str(path)]


def test_default_out_dir(tmp_path):
    """The output dir lives under XDG_CONFIG_HOME/hueberry."""
    assert waybar.default_out_dir() == tmp_path / "hueberry" / "sysmon"


def test_write_files_defaults_copy_style(tmp_path):
    """write_files creates the dir, writes the config and copies the style."""
    config_path = tmp_path / "sysmon.json"
    cfg_file, style = waybar.write_files(SysmonConfig(), config_path)
    assert cfg_file == tmp_path / "hueberry" / "sysmon" / "config.json"
    written = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert written == json.loads(json.dumps(
        waybar.build_waybar_config(SysmonConfig(), config_path)))
    bundled = files("hueberry.data").joinpath("sysmon/style.css").read_bytes()
    assert style.read_bytes() == bundled


def test_write_files_keeps_existing_style(tmp_path):
    """An existing style sheet is never overwritten."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "style.css").write_bytes(USER_STYLE)
    _cfg, style = waybar.write_files(SysmonConfig(), tmp_path / "s.json", out_dir)
    assert style.read_bytes() == USER_STYLE
