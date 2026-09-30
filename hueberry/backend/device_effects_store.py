# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Remember the hardware effect last applied per device zone (device_effects.json).

OpenRazer cannot read an effect back, so Hueberry records what it applied:
``{"version": 1, "devices": {serial: {zone_key: {"effect": key, "params": {...}}}}}``.
``params`` hold exactly what :func:`hueberry.backend.lighting.apply_effect`
receives for the effect (colours as ``[r, g, b]`` lists, speed and direction as
ints). Saves are atomic and mode 0600 (see :mod:`hueberry.config_files`); an
unparseable file is moved aside to ``.bak``. A module lock serializes access.
"""

import logging
import threading
from pathlib import Path
from typing import Any, Mapping

from hueberry import config_files
from hueberry.backend.lighting import (
    DIRECTION_VALUES, EFFECTS, PARAM_COLOUR1, PARAM_COLOUR2, PARAM_TIME, TIME_VALUES,
    validate_colour,
)

__all__ = ["config_path", "load_record", "save_record"]

logger = logging.getLogger(__name__)

CONFIG_FILE_NAME = "device_effects.json"
SCHEMA_VERSION = 1
VERSION_KEY = "version"
DEVICES_KEY = "devices"
EFFECT_KEY = "effect"
PARAMS_KEY = "params"
TEMP_PREFIX = ".device-effects-"
QUARANTINE_KIND = "device effects file"
COLOUR_PARAMS = (PARAM_COLOUR1, PARAM_COLOUR2)

_lock = threading.Lock()


def config_path() -> Path:
    """``$XDG_CONFIG_HOME/hueberry/device_effects.json`` (default ``~/.config``)."""
    return config_files.config_dir() / CONFIG_FILE_NAME


def _choice(name: str, value: Any, allowed: tuple[int, ...]) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value not in allowed:
        raise ValueError(f"Invalid {name} {value!r}; expected one of {allowed}")
    return value


def _normalise(effect_key: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    """The JSON form of ``params`` for ``effect_key``; anything invalid raises ValueError."""
    effect = EFFECTS.get(effect_key) if isinstance(effect_key, str) else None
    if effect is None:
        raise ValueError(f"Unknown effect {effect_key!r}")
    if not isinstance(params, Mapping):
        raise ValueError(f"Effect parameters must be a mapping, got {params!r}")
    result: dict[str, Any] = {}
    for name in effect.params:
        if name not in params:
            raise ValueError(f"Effect {effect.key!r} needs parameter {name!r}")
        value = params[name]
        if name in COLOUR_PARAMS:
            result[name] = list(validate_colour(value))
        elif name == PARAM_TIME:
            result[name] = _choice(name, value, TIME_VALUES)
        else:
            result[name] = _choice(name, value, DIRECTION_VALUES)
    return result


def _parse(raw: bytes) -> dict[str, Any]:
    """The ``devices`` mapping of the file; a bad file raises ValueError."""
    data = config_files.parse_json(raw)
    if not isinstance(data, dict) or data.get(VERSION_KEY) != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema version (expected {SCHEMA_VERSION})")
    devices = data.get(DEVICES_KEY)
    if not isinstance(devices, dict):
        raise ValueError(f"{DEVICES_KEY!r} must be an object")
    return devices


def _read(path: Path) -> dict[str, Any]:
    """The stored devices (empty when missing, unreadable or corrupt; logged)."""
    devices, error = config_files.load_file(path, QUARANTINE_KIND, _parse, dict)
    if error is not None:
        logger.warning("Ignoring recorded device effects: %s", error)
    return devices


def load_record(serial: str, zone_key: str,
                path: Path | None = None) -> tuple[str, dict[str, Any]] | None:
    """``(effect_key, params)`` last recorded for ``zone_key`` of ``serial``, or None.

    An invalid entry is logged and None; this never raises.
    """
    try:
        with _lock:
            devices = _read(path if path is not None else config_path())
        zones = devices.get(serial)
        entry = zones.get(zone_key) if isinstance(zones, dict) else None
        if entry is None:
            return None
        if not isinstance(entry, dict):
            raise ValueError(f"entry must be an object, got {entry!r}")
        effect_key = entry.get(EFFECT_KEY)
        params = _normalise(effect_key, entry.get(PARAMS_KEY, {}))
        return effect_key, params
    except Exception as exc:  # a bad record must never break the caller
        logger.warning("Ignoring recorded effect of %s/%s: %s", serial, zone_key, exc)
        return None


def save_record(serial: str, zone_key: str, effect_key: str, params: Mapping[str, Any],
                path: Path | None = None) -> None:
    """Record ``effect_key`` with ``params`` for ``zone_key`` of ``serial``.

    Raises ValueError for an invalid effect or parameters and OSError for I/O
    failures; the previous file is then untouched.
    """
    entry = {EFFECT_KEY: effect_key, PARAMS_KEY: _normalise(effect_key, params)}
    path = path if path is not None else config_path()
    with _lock:
        devices = _read(path)
        zones = devices.get(serial)
        if not isinstance(zones, dict):
            zones = devices[serial] = {}
        zones[zone_key] = entry
        data = {VERSION_KEY: SCHEMA_VERSION, DEVICES_KEY: devices}
        config_files.atomic_write(path, config_files.dump_json(data), temp_prefix=TEMP_PREFIX)
    logger.info("Recorded effect %s for %s/%s", effect_key, serial, zone_key)
