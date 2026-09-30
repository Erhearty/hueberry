# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""System monitor configuration: data model, validation and ``sysmon.json`` store.

This module must stay free of PyQt imports: the metrics collector runs as a
plain subprocess and imports it. The model is split in two checks, mirroring
``hueberry.macros.model``: ``from_dict`` rejects a bad shape or wrong types
(raising SysmonConfigError), while ``problems`` lists values of the right type
that are out of range. ``validate`` raises when there are any problems.

Flat field layout of ``SysmonConfig`` (also the JSON keys, plus ``version``):

* ``enabled`` - overlay shown on start.
* ``show_cpu``, ``show_gpu``, ``show_vram``, ``show_ram``, ``show_disks`` -
  which metrics are displayed.
* ``disks`` - tuple of DiskSpec; empty means auto-detect.
* ``gpu_card`` - ``"auto"`` or a DRM card name such as ``card1``.
* ``align_x`` / ``align_y`` / ``orientation`` - one of ALIGNS_X / ALIGNS_Y /
  ORIENTATIONS. ``align_x`` (left/center/right) and ``align_y``
  (top/center/bottom) together place the overlay, e.g. right + top is the
  top-right corner; both center is not allowed. A legacy ``edge`` key from
  older files is migrated on load: top/bottom set ``align_y``, left/right set
  ``align_x`` and centre ``align_y``; any other value is dropped.
* ``margin_top``, ``margin_right``, ``margin_bottom``, ``margin_left`` - pixels.
* ``width``, ``height`` - pixels, 0 means automatic.
* ``interval_s`` - sampling interval in seconds.
"""

import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hueberry import config_files

logger = logging.getLogger(__name__)

ALIGN_LEFT = "left"
ALIGN_RIGHT = "right"
ALIGN_TOP = "top"
ALIGN_BOTTOM = "bottom"
ALIGN_CENTER = "center"
ALIGNS_X = (ALIGN_LEFT, ALIGN_CENTER, ALIGN_RIGHT)
ALIGNS_Y = (ALIGN_TOP, ALIGN_CENTER, ALIGN_BOTTOM)
ORIENTATION_ROW = "row"
ORIENTATION_STACKED = "stacked"
ORIENTATIONS = (ORIENTATION_ROW, ORIENTATION_STACKED)
METRICS = ("cpu", "gpu", "vram", "ram", "disks")
METRIC_FIELD_PREFIX = "show_"  # metric "cpu" is field "show_cpu"
MARGIN_SIDES = ("top", "right", "bottom", "left")
MARGIN_FIELD_PREFIX = "margin_"  # side "top" is field "margin_top"
GPU_CARD_AUTO = "auto"
GPU_CARD_RE = re.compile(r"card[0-9]+")
DISK_DEVICE_RE = re.compile(r"[a-z0-9]+")  # a block device name, never a path

MIN_MARGIN = 0
MAX_MARGIN = 2000
MIN_SIZE_PX = 0  # 0 = automatic size
MAX_SIZE_PX = 10_000
MIN_INTERVAL_S = 0.5
MAX_INTERVAL_S = 10.0
MAX_DISKS = 16
MAX_DISK_LABEL_LENGTH = 32

DEFAULT_ENABLED = False
DEFAULT_GPU_CARD = GPU_CARD_AUTO
DEFAULT_ALIGN_X = ALIGN_RIGHT
DEFAULT_ALIGN_Y = ALIGN_TOP
DEFAULT_ORIENTATION = ORIENTATION_ROW
DEFAULT_MARGIN_TOP = 40
DEFAULT_MARGIN_RIGHT = 20
DEFAULT_MARGIN_BOTTOM = 0
DEFAULT_MARGIN_LEFT = 0
DEFAULT_WIDTH = 500
DEFAULT_HEIGHT = 0
DEFAULT_INTERVAL_S = 1.0

SCHEMA_VERSION = 1
VERSION_KEY = "version"
CONFIG_FILE_NAME = "sysmon.json"
TEMP_PREFIX = ".sysmon-"
QUARANTINE_KIND = "sysmon config"  # log wording: "Corrupt sysmon config ..."

_BOOL_FIELDS = ("enabled",) + tuple(METRIC_FIELD_PREFIX + name for name in METRICS)
_STR_FIELDS = ("gpu_card", "align_x", "align_y", "orientation")
_MARGIN_FIELDS = tuple(MARGIN_FIELD_PREFIX + side for side in MARGIN_SIDES)
_SIZE_FIELDS = ("width", "height")
_TYPED_FIELDS = ((bool, _BOOL_FIELDS), (str, _STR_FIELDS), (int, _MARGIN_FIELDS + _SIZE_FIELDS))
_CHOICES = (("align_x", ALIGNS_X), ("align_y", ALIGNS_Y), ("orientation", ORIENTATIONS))
LEGACY_EDGE_KEY = "edge"  # removed setting, migrated by _migrate_edge
_LEGACY_EDGES_Y = (ALIGN_TOP, ALIGN_BOTTOM)
_LEGACY_EDGES_X = (ALIGN_LEFT, ALIGN_RIGHT)


class SysmonConfigError(ValueError):
    """Sysmon configuration data that is malformed or violates a limit."""


def _field(data: Any, key: str, kind: type) -> Any:
    """Fetch ``data[key]`` insisting on ``kind`` (bools are not ints here)."""
    if not isinstance(data, dict):
        raise SysmonConfigError(f"expected an object holding {key!r}")
    value = data.get(key)
    if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
        raise SysmonConfigError(f"{key!r} must be {kind.__name__}, got {type(value).__name__}")
    return value


def _optional(data: Any, key: str, kind: type, default: Any) -> Any:
    """Like ``_field`` but a missing ``key`` yields ``default``."""
    if not isinstance(data, dict):
        raise SysmonConfigError(f"expected an object holding {key!r}")
    if key not in data:
        return default
    return _field(data, key, kind)


def _migrate_edge(data: dict[str, Any]) -> dict[str, Any]:
    """Shallow copy of ``data`` with a legacy ``edge`` key folded into the aligns.

    top/bottom set ``align_y``; left/right set ``align_x`` and centre
    ``align_y``. Any other value (even a non-string) is simply dropped so a
    stray edge never makes loading fail.
    """
    migrated = dict(data)
    edge = migrated.pop(LEGACY_EDGE_KEY, None)
    if edge in _LEGACY_EDGES_Y:
        migrated["align_y"] = edge
    elif edge in _LEGACY_EDGES_X:
        migrated["align_x"] = edge
        migrated["align_y"] = ALIGN_CENTER
    return migrated


def _optional_number(data: Any, key: str, default: float) -> float:
    """Fetch an int or float ``data[key]`` as float (bools rejected); missing is ``default``."""
    value = _optional(data, key, object, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SysmonConfigError(f"{key!r} must be a number, got {type(value).__name__}")
    return float(value)


@dataclass(frozen=True)
class DiskSpec:
    """One monitored block device: kernel name, display label and full-scale MB/s."""

    device: str
    label: str
    max_mbps: float

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready representation."""
        return {"device": self.device, "label": self.label, "max_mbps": self.max_mbps}

    @classmethod
    def from_dict(cls, data: Any) -> "DiskSpec":
        """Build from JSON data; a missing label defaults to the device name."""
        device = _field(data, "device", str)
        label = _optional(data, "label", str, device)
        return cls(device, label, _optional_number(data, "max_mbps", math.nan))

    def problems(self) -> list[str]:
        """Human-readable descriptions of out-of-range values (empty if valid)."""
        found = []
        if not DISK_DEVICE_RE.fullmatch(self.device):
            found.append(f"disk device {self.device!r} must be a device name like 'sda'")
        if not self.label or len(self.label) > MAX_DISK_LABEL_LENGTH:
            found.append(f"disk label {self.label!r} must be 1-{MAX_DISK_LABEL_LENGTH} characters")
        if not (math.isfinite(self.max_mbps) and self.max_mbps > 0):
            found.append(f"disk {self.device!r} max_mbps must be a positive number")
        return found


@dataclass(frozen=True)
class SysmonConfig:
    """The whole overlay configuration; see the module docstring for fields."""

    enabled: bool = DEFAULT_ENABLED
    show_cpu: bool = True
    show_gpu: bool = True
    show_vram: bool = True
    show_ram: bool = True
    show_disks: bool = True
    disks: tuple[DiskSpec, ...] = ()
    gpu_card: str = DEFAULT_GPU_CARD
    align_x: str = DEFAULT_ALIGN_X
    align_y: str = DEFAULT_ALIGN_Y
    orientation: str = DEFAULT_ORIENTATION
    margin_top: int = DEFAULT_MARGIN_TOP
    margin_right: int = DEFAULT_MARGIN_RIGHT
    margin_bottom: int = DEFAULT_MARGIN_BOTTOM
    margin_left: int = DEFAULT_MARGIN_LEFT
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    interval_s: float = DEFAULT_INTERVAL_S

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready representation (without the schema version)."""
        data: dict[str, Any] = {}
        for _kind, names in _TYPED_FIELDS:
            data.update({name: getattr(self, name) for name in names})
        data["disks"] = [disk.to_dict() for disk in self.disks]
        data["interval_s"] = self.interval_s
        return data

    @classmethod
    def from_dict(cls, data: Any) -> "SysmonConfig":
        """Build from JSON data; missing keys take defaults, wrong types raise."""
        if not isinstance(data, dict):
            raise SysmonConfigError("sysmon config must be an object")
        if LEGACY_EDGE_KEY in data:
            data = _migrate_edge(data)
        defaults = cls()
        values: dict[str, Any] = {}
        for kind, names in _TYPED_FIELDS:
            values.update({name: _optional(data, name, kind, getattr(defaults, name))
                           for name in names})
        values["interval_s"] = _optional_number(data, "interval_s", defaults.interval_s)
        raw_disks = _optional(data, "disks", list, [])
        if len(raw_disks) > MAX_DISKS:
            raise SysmonConfigError(f"at most {MAX_DISKS} disks are allowed")
        values["disks"] = tuple(DiskSpec.from_dict(item) for item in raw_disks)
        return cls(**values)

    def problems(self) -> list[str]:
        """Human-readable descriptions of out-of-range values (empty if valid)."""
        return self._choice_problems() + self._range_problems() + self._disk_problems()

    def validate(self) -> None:
        """Raise SysmonConfigError listing every problem, if there are any."""
        found = self.problems()
        if found:
            raise SysmonConfigError("; ".join(found))

    def _choice_problems(self) -> list[str]:
        """Enumerated fields holding a value outside their allowed set."""
        found = [f"{name} must be one of {', '.join(allowed)}, got {getattr(self, name)!r}"
                 for name, allowed in _CHOICES if getattr(self, name) not in allowed]
        if self.gpu_card != GPU_CARD_AUTO and not GPU_CARD_RE.fullmatch(self.gpu_card):
            found.append(f"gpu_card must be {GPU_CARD_AUTO!r} or like 'card0', "
                         f"got {self.gpu_card!r}")
        if self.align_x == self.align_y == ALIGN_CENTER:
            found.append("align_x and align_y cannot both be center")
        return found

    def _range_problems(self) -> list[str]:
        """Numeric fields outside their bounds."""
        bounds = [(name, MIN_MARGIN, MAX_MARGIN) for name in _MARGIN_FIELDS]
        bounds += [(name, MIN_SIZE_PX, MAX_SIZE_PX) for name in _SIZE_FIELDS]
        bounds.append(("interval_s", MIN_INTERVAL_S, MAX_INTERVAL_S))
        return [f"{name} must be between {low} and {high}, got {getattr(self, name)}"
                for name, low, high in bounds if not low <= getattr(self, name) <= high]

    def _disk_problems(self) -> list[str]:
        """Problems of each disk, plus too many or duplicated devices."""
        found = [problem for disk in self.disks for problem in disk.problems()]
        if len(self.disks) > MAX_DISKS:
            found.append(f"at most {MAX_DISKS} disks are allowed")
        devices = [disk.device for disk in self.disks]
        if len(set(devices)) != len(devices):
            found.append("each disk device may be listed only once")
        return found


def config_path() -> Path:
    """``$XDG_CONFIG_HOME/hueberry/sysmon.json`` (default ``~/.config``)."""
    return config_files.config_dir() / CONFIG_FILE_NAME


def _parse(raw: bytes) -> SysmonConfig:
    """Parse and fully validate file contents; any problem raises ValueError."""
    data = config_files.parse_json(raw)
    if not isinstance(data, dict) or data.get(VERSION_KEY) != SCHEMA_VERSION:
        raise SysmonConfigError(f"unsupported schema version (expected {SCHEMA_VERSION})")
    config = SysmonConfig.from_dict(data)
    config.validate()
    return config


def load_with_error(path: Path | None = None) -> tuple[SysmonConfig, str | None]:
    """Return ``(config, error)``; a missing file is the defaults without an error.

    A corrupt or invalid file is moved aside to ``.bak`` and the defaults are
    returned together with a message describing what happened.
    """
    path = path if path is not None else config_path()
    return config_files.load_file(path, QUARANTINE_KIND, _parse, SysmonConfig)


def load(path: Path | None = None) -> SysmonConfig:
    """Return the stored config, or the defaults when missing or corrupt."""
    config, error = load_with_error(path)
    if error:
        logger.warning("Using default sysmon config: %s", error)
    return config


def save(config: SysmonConfig, path: Path | None = None) -> None:
    """Validate, then atomically replace the file (mode 0600).

    Raises SysmonConfigError for invalid configs and OSError for I/O failures;
    on any failure the previous file is untouched.
    """
    config.validate()
    path = path if path is not None else config_path()
    payload = config_files.dump_json({VERSION_KEY: SCHEMA_VERSION, **config.to_dict()})
    config_files.atomic_write(path, payload, temp_prefix=TEMP_PREFIX)
    logger.info("Saved sysmon config to %s", path)
