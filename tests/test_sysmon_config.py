# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the sysmon config model and its sysmon.json store."""

import dataclasses
import json

import pytest

from hueberry.sysmon import config as sc

NVME = sc.DiskSpec("nvme0n1", "NVMe", 1073.0)
SATA = sc.DiskSpec("sda", "SSD", 175.0)
CUSTOM = sc.SysmonConfig(enabled=True, show_vram=False, disks=(NVME, SATA), gpu_card="card1",
                         align_x=sc.ALIGN_LEFT, align_y=sc.ALIGN_CENTER,
                         orientation=sc.ORIENTATION_STACKED, margin_top=5, margin_left=7,
                         width=0, height=300, interval_s=2.5)


@pytest.fixture(autouse=True)
def _config_home(monkeypatch, tmp_path):
    """Point XDG_CONFIG_HOME at a per-test temp directory."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


def test_defaults():
    """Defaults match the documented overlay layout."""
    cfg = sc.SysmonConfig()
    assert cfg.enabled is False
    assert all(getattr(cfg, sc.METRIC_FIELD_PREFIX + name) for name in sc.METRICS)
    assert cfg.disks == ()
    assert (cfg.gpu_card, cfg.align_x, cfg.align_y, cfg.orientation) == (
        "auto", "right", "top", "row")
    assert (cfg.margin_top, cfg.margin_right, cfg.margin_bottom, cfg.margin_left) == (
        40, 20, 0, 0)
    assert (cfg.width, cfg.height, cfg.interval_s) == (500, 0, 1.0)
    assert cfg.problems() == []


def test_module_does_not_import_qt():
    """The collector subprocess imports the config module without PyQt."""
    with open(sc.__file__, encoding="utf-8") as handle:
        imports = [line for line in handle if line.startswith(("import ", "from "))]
    assert imports
    assert not any("PyQt" in line for line in imports)


def test_dict_round_trip():
    """to_dict/from_dict preserve every field, including disks."""
    assert CUSTOM.problems() == []
    assert sc.SysmonConfig.from_dict(CUSTOM.to_dict()) == CUSTOM
    assert sc.SysmonConfig.from_dict(json.loads(json.dumps(CUSTOM.to_dict()))) == CUSTOM


def test_from_dict_missing_keys_default():
    """An empty object is the default config; a disk label defaults to its device."""
    assert sc.SysmonConfig.from_dict({}) == sc.SysmonConfig()
    cfg = sc.SysmonConfig.from_dict({"disks": [{"device": "sda", "max_mbps": 175}],
                                     "interval_s": 2})
    assert cfg.disks == (sc.DiskSpec("sda", "sda", 175.0),)
    assert cfg.interval_s == 2.0


@pytest.mark.parametrize("edge", ["weird", 3, None, ["left"]])
def test_from_dict_ignores_stray_edge_key(edge):
    """An unknown legacy 'edge' value is dropped and the config still loads."""
    assert sc.SysmonConfig.from_dict({"edge": edge}) == sc.SysmonConfig()


@pytest.mark.parametrize(("data", "expected"), [
    ({"edge": "top", "align_x": "left", "align_y": "bottom"}, ("left", "top")),
    ({"edge": "bottom", "align_x": "center", "align_y": "top"}, ("center", "bottom")),
    ({"edge": "left", "align_x": "right", "align_y": "top"}, ("left", "center")),
    ({"edge": "right", "align_x": "left", "align_y": "bottom"}, ("right", "center")),
    ({"edge": "left", "align_y": "center", "align_x": "right"}, ("left", "center")),
    ({"edge": "left", "align_x": "center", "align_y": "center"}, ("left", "center")),
])
def test_from_dict_migrates_legacy_edge(data, expected):
    """A legacy 'edge' overrides conflicting stored aligns and yields a valid config."""
    cfg = sc.SysmonConfig.from_dict(data)
    assert (cfg.align_x, cfg.align_y) == expected
    assert cfg.problems() == []


def test_legacy_edge_file_loads_without_quarantine():
    """A saved file with 'edge' and center/center aligns loads, keeping other settings."""
    path = sc.config_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"version": 1, "edge": "left", "align_x": "center",
                                "align_y": "center", "margin_top": 7}), encoding="utf-8")
    config, error = sc.load_with_error()
    assert error is None
    assert (config.align_x, config.align_y) == ("left", "center")
    assert config.margin_top == 7


@pytest.mark.parametrize("data", [
    [],
    {"enabled": 1},
    {"width": True},
    {"width": "500"},
    {"align_x": 3},
    {"interval_s": "1"},
    {"interval_s": False},
    {"disks": {}},
    {"disks": ["sda"]},
    {"disks": [{"label": "x", "max_mbps": 1}]},
    {"disks": [{"device": "sda", "max_mbps": "fast"}]},
    {"disks": [{"device": f"sd{index}", "max_mbps": 1} for index in range(sc.MAX_DISKS + 1)]},
])
def test_from_dict_rejects_bad_shape(data):
    """Wrong shapes and types raise SysmonConfigError (a ValueError)."""
    with pytest.raises(sc.SysmonConfigError):
        sc.SysmonConfig.from_dict(data)


@pytest.mark.parametrize("changes", [
    {"disks": (sc.DiskSpec("/dev/sda", "SSD", 175.0),)},
    {"disks": (sc.DiskSpec("../sda", "SSD", 175.0),)},
    {"disks": (sc.DiskSpec("sda", "SSD", 0.0),)},
    {"disks": (sc.DiskSpec("sda", "SSD", -1.0),)},
    {"disks": (sc.DiskSpec("sda", "", 175.0),)},
    {"disks": (SATA, SATA)},
    {"gpu_card": "/dev/dri/card0"},
    {"gpu_card": "card"},
    {"gpu_card": "card0\n"},
    {"align_x": "top"},
    {"align_y": "left"},
    {"align_x": "start"},
    {"align_x": sc.ALIGN_CENTER, "align_y": sc.ALIGN_CENTER},
    {"orientation": "column"},
    {"margin_top": -1},
    {"margin_left": sc.MAX_MARGIN + 1},
    {"width": -1},
    {"height": sc.MAX_SIZE_PX + 1},
    {"interval_s": 0.4},
    {"interval_s": 10.5},
])
def test_problems_reject_out_of_range(changes):
    """Each out-of-range value is reported and makes validate raise."""
    cfg = dataclasses.replace(sc.SysmonConfig(), **changes)
    assert len(cfg.problems()) == 1
    with pytest.raises(sc.SysmonConfigError):
        cfg.validate()


def test_bounds_are_inclusive():
    """The documented limits themselves are valid."""
    cfg = sc.SysmonConfig(margin_top=sc.MAX_MARGIN, margin_bottom=sc.MIN_MARGIN,
                          width=sc.MAX_SIZE_PX, interval_s=sc.MIN_INTERVAL_S)
    assert cfg.problems() == []
    assert dataclasses.replace(cfg, interval_s=sc.MAX_INTERVAL_S).problems() == []


def test_missing_file_is_defaults(tmp_path):
    """No sysmon.json yet means the defaults, without an error."""
    assert sc.config_path() == tmp_path / "hueberry" / "sysmon.json"
    assert sc.load() == sc.SysmonConfig()
    assert sc.load_with_error() == (sc.SysmonConfig(), None)


def test_save_load_round_trip(tmp_path):
    """save writes a versioned file that load reads back unchanged."""
    sc.save(CUSTOM)
    path = tmp_path / "hueberry" / "sysmon.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == sc.SCHEMA_VERSION
    assert sc.load() == CUSTOM
    assert sc.load(path) == CUSTOM


def test_save_rejects_invalid_config():
    """An invalid config is never written."""
    with pytest.raises(sc.SysmonConfigError):
        sc.save(sc.SysmonConfig(align_x="middle"))
    assert not sc.config_path().exists()


@pytest.mark.parametrize("content", [
    b"{not json",
    b'{"version": 99}',
    b'{"version": 1, "width": "wide"}',
    b'{"version": 1, "interval_s": 60}',
])
def test_corrupt_file_moved_to_bak(content):
    """A corrupt or invalid file is quarantined to .bak and defaults are used."""
    path = sc.config_path()
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    config, error = sc.load_with_error()
    assert config == sc.SysmonConfig()
    assert error is not None
    assert not path.exists()
    assert path.with_name("sysmon.json.bak").read_bytes() == content


def test_load_returns_defaults_for_corrupt_file():
    """load() itself swallows the error after quarantining."""
    path = sc.config_path()
    path.parent.mkdir(parents=True)
    path.write_bytes(b"[]")
    assert sc.load() == sc.SysmonConfig()
    assert path.with_name("sysmon.json.bak").exists()
