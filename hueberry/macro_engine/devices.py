# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Input device discovery, stable identities and permission checks."""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)

VIRTUAL_PREFIX = "hueberry-virtual:"
UINPUT_PATH = "/dev/uinput"
INPUT_DIR = "/dev/input"
EVENT_NODE_GLOB = "event*"


@dataclass(frozen=True)
class DeviceEntry:
    """One input device node as seen by the engine."""

    identity: str
    path: str
    name: str
    has_keys: bool


@dataclass(frozen=True)
class PermissionReport:
    """What the engine may access: uinput for output, event nodes for input."""

    uinput_ok: bool
    unreadable_inputs: tuple[str, ...]


def identity(dev: Any) -> str:
    """Identity that survives replugs and reboots (``/dev/input/eventN`` does not).

    ``uniq`` (serial) is preferred; ``phys`` (USB port path) distinguishes two
    identical devices without serials.
    """
    info = dev.info
    return f"{info.vendor:04x}:{info.product:04x}:{dev.name}:{dev.uniq or dev.phys}"


def is_virtual(name: str) -> bool:
    """True for our own uinput clones, which must never be grabbed again."""
    return name.startswith(VIRTUAL_PREFIX)


def has_keys(dev: Any) -> bool:
    """True when the device reports any EV_KEY codes (keys or buttons)."""
    from evdev import ecodes  # lazy: optional dependency

    return bool(dev.capabilities().get(ecodes.EV_KEY))


def list_device_paths() -> list[str]:
    """Readable event nodes, via python-evdev."""
    import evdev  # lazy: optional dependency

    return list(evdev.list_devices())


def open_device(path: str) -> Any:
    """Open an event node as ``evdev.InputDevice`` (not grabbed)."""
    import evdev  # lazy: optional dependency

    return evdev.InputDevice(path)


def _describe(path: str, open_fn: Callable[[str], Any]) -> DeviceEntry | None:
    try:
        dev = open_fn(path)
    except OSError as exc:  # unplugged or unreadable since listing
        logger.info("Skipping %s: %s", path, exc)
        return None
    try:
        if is_virtual(dev.name):
            return None
        return DeviceEntry(identity(dev), path, dev.name, has_keys(dev))
    finally:
        dev.close()


def discover(
    list_devices: Callable[[], Iterable[str]] | None = None,
    open: Callable[[str], Any] | None = None,  # noqa: A002 - mirrors the plan's API
) -> list[DeviceEntry]:
    """Describe every readable input device except Hueberry's virtual clones."""
    list_fn = list_devices if list_devices is not None else list_device_paths
    open_fn = open if open is not None else open_device
    entries = (_describe(path, open_fn) for path in list_fn())
    return [entry for entry in entries if entry is not None]


def _event_nodes() -> list[str]:
    return sorted(str(path) for path in Path(INPUT_DIR).glob(EVENT_NODE_GLOB))


def check_permissions(
    access: Callable[[str, int], bool] = os.access,
    list_nodes: Callable[[], Iterable[str]] = _event_nodes,
) -> PermissionReport:
    """Report uinput access and unreadable event nodes, so the UI can explain
    the udev rule / ``input`` group setup instead of failing silently."""
    uinput_ok = bool(access(UINPUT_PATH, os.R_OK | os.W_OK))
    unreadable = tuple(node for node in list_nodes() if not access(node, os.R_OK))
    return PermissionReport(uinput_ok, unreadable)
