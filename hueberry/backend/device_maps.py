# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Which vendored device-map SVG draws which device.

The maps come from Polychromatic (``data/devicemaps``): ``maps.json`` names
each graphic by device name, optionally suffixed with a locale in brackets
(``"Razer BlackWidow (en_GB)"``), with the SVG file name, the LED matrix size
(``rows`` x ``cols``) and the keyboard locale. A missing or broken index never
raises: it just means no device has a graphic.

Pure data only: nothing here imports PyQt6.
"""

import json
import locale as system_locale
import logging
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any, Iterable

__all__ = ["DeviceMap", "load_index", "svg_bytes", "match"]

logger = logging.getLogger(__name__)

DATA_PACKAGE = "hueberry.data"
MAPS_DIR = "devicemaps"
INDEX_FILE = "maps.json"
FALLBACK_LOCALE = "en_US"
SUFFIX_OPEN = " ("  # a key like "Name (en_GB)" is "Name" for a locale
SUFFIX_CLOSE = ")"
INDEX_ENCODING = "utf-8"

# Device names (as ``_normalise`` gives them) drawn with another device's map.
MAP_ALIASES: dict[str, str] = {
    # Polychromatic has no base-V4 map; the BlackWidow V4 (PID 0x0287) has the
    # same 8x23 matrix as the V4 Pro.
    "razer blackwidow v4": "razer blackwidow v4 pro",
}


@dataclass(frozen=True)
class DeviceMap:
    """One entry of ``maps.json``: the graphic of a device name at a matrix size."""

    name: str
    filename: str
    rows: int
    cols: int
    locale: str | None


def _default_root() -> Any:
    """The packaged ``devicemaps`` directory (a Traversable)."""
    return resources.files(DATA_PACKAGE) / MAPS_DIR


def _entry(name: str, raw: Any) -> DeviceMap | None:
    """The DeviceMap of one index entry, or None when it lacks a usable field."""
    try:
        locale = raw.get("locale")
        return DeviceMap(name, str(raw["filename"]), int(raw["rows"]), int(raw["cols"]),
                         str(locale) if locale else None)
    except (AttributeError, KeyError, TypeError, ValueError):
        logger.debug("Skipping device map entry %r without filename/rows/cols", name)
        return None


def _read_index(root: Any) -> dict[str, DeviceMap]:
    """Parse ``maps.json`` under ``root``; a missing or invalid index gives {}."""
    try:
        raw = json.loads((root / INDEX_FILE).read_text(encoding=INDEX_ENCODING))
    except (OSError, ValueError) as exc:
        logger.warning("Device map index %s is unavailable: %s", root, exc)
        return {}
    if not isinstance(raw, dict):
        logger.warning("Device map index %s is not a JSON object", root)
        return {}
    index = {}
    for name, value in raw.items():
        device_map = _entry(name, value)
        if device_map is not None:
            index[name] = device_map
    return index


@lru_cache(maxsize=None)
def _default_index() -> dict[str, DeviceMap]:
    """The packaged index, read once."""
    try:
        root = _default_root()
    except (ImportError, OSError, TypeError) as exc:
        logger.warning("Device maps package %s is unavailable: %s", DATA_PACKAGE, exc)
        return {}
    return _read_index(root)


def load_index(root: Any = None) -> dict[str, DeviceMap]:
    """Every device map keyed by its ``maps.json`` name; ``root`` overrides the package data.

    ``root`` is a directory Path or Traversable holding ``maps.json``. Never raises:
    a missing or invalid index is logged and gives an empty dict.
    """
    if root is None:
        return dict(_default_index())
    return _read_index(root)


def svg_bytes(device_map: DeviceMap, root: Any = None) -> bytes | None:
    """The SVG file of ``device_map``, or None (logged) when it cannot be read."""
    try:
        base = _default_root() if root is None else root
        return (base / device_map.filename).read_bytes()
    except (ImportError, OSError, TypeError) as exc:
        logger.warning("Device map %s is unavailable: %s", device_map.filename, exc)
        return None


def _normalise(name: str) -> str:
    return (name or "").strip().casefold()


def _base_name(key: str) -> str:
    """``key`` without a trailing ``" (...)"`` suffix."""
    key = key.strip()
    if key.endswith(SUFFIX_CLOSE) and SUFFIX_OPEN in key:
        return key[:key.rindex(SUFFIX_OPEN)]
    return key


def _system_locale() -> str | None:
    try:
        return system_locale.getlocale()[0]
    except ValueError:  # an unknown locale in the environment
        return None


def _first(maps: Iterable[DeviceMap]) -> DeviceMap | None:
    return next(iter(maps), None)


def _prefer(candidates: list[tuple[str, DeviceMap]], wanted: str,
            locale: str | None) -> DeviceMap | None:
    """Exact key, then ``locale``, then en_US, then the first in key order."""
    maps = [device_map for _, device_map in candidates]
    return (_first(m for key, m in candidates if _normalise(key) == wanted)
            or (_first(m for m in maps if m.locale == locale) if locale else None)
            or _first(m for m in maps if m.locale == FALLBACK_LOCALE)
            or _first(maps))


def _candidates(entries: dict[str, DeviceMap], wanted: str, rows: int,
                cols: int) -> list[tuple[str, DeviceMap]]:
    """The (key, map) pairs named ``wanted`` at ``rows`` x ``cols``, in key order."""
    return [(key, device_map) for key, device_map in sorted(entries.items())
            if wanted in (_normalise(key), _normalise(_base_name(key)))
            and device_map.rows == rows and device_map.cols == cols]


def match(name: str, rows: int, cols: int, index: dict[str, DeviceMap] | None = None,
          locale: str | None = None) -> DeviceMap | None:
    """The graphic of device ``name`` with a ``rows`` x ``cols`` matrix, or None.

    Names compare trimmed and case-insensitive, with or without a key's locale
    suffix; ``locale`` defaults to the system locale. When ``name`` itself has no
    map of that size, its ``MAP_ALIASES`` target is tried once, with the same
    size check and locale preference.
    """
    entries = load_index() if index is None else index
    wanted = _normalise(name)
    candidates = _candidates(entries, wanted, rows, cols)
    alias = MAP_ALIASES.get(wanted)
    if not candidates and alias:
        wanted = _normalise(alias)
        candidates = _candidates(entries, wanted, rows, cols)
    if not candidates:
        return None
    return _prefer(candidates, wanted, locale if locale is not None else _system_locale())
