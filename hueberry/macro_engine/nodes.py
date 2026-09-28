# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Node registry helpers: one physical device, several evdev nodes.

A USB device exposes one event node per interface, all sharing one identity
(see ``devices.identity``). The engine opens, remaps and records per node
(handles and node states are keyed by node path) but reports per identity,
folding the node states together here.
"""

import logging
import selectors
from typing import Any, Callable, Iterable

from hueberry.macro_engine.devices import KIND_OTHER
from hueberry.macro_engine.handles import DeviceHandle
from hueberry.macro_engine.remapper import (
    STATE_ACTIVE,
    STATE_BUSY,
    STATE_ERROR,
    STATE_INACTIVE,
    STATE_PERMISSION_DENIED,
    STATE_WAITING,
)

logger = logging.getLogger(__name__)

STATE_DISCONNECTED = "disconnected"
# Worst first: an identity reports the state of its worst node. Inactive nodes
# (none of the triggers on that interface) and any other state are ignored.
STATE_PRECEDENCE = (
    STATE_ERROR, STATE_DISCONNECTED, STATE_PERMISSION_DENIED, STATE_BUSY, STATE_WAITING, STATE_ACTIVE,
)


def node_state(identity: str, name: str, state: str, error: str | None) -> dict:
    """The state record kept for one node (keyed by its path)."""
    return {"identity": identity, "name": name, "state": state, "error": error}


def remapper_state(handle: DeviceHandle) -> dict:
    """The node state of ``handle`` taken from its remapper."""
    remapper = handle.remapper
    return node_state(handle.identity, handle.name, remapper.state, remapper.error)


def _fold(states: list[dict]) -> dict:
    """One ``{name, state, error}`` for the nodes of one identity."""
    ranked = [state for state in states if state["state"] in STATE_PRECEDENCE]
    if not ranked:
        return {"name": states[0]["name"], "state": STATE_INACTIVE, "error": None}
    worst = min(ranked, key=lambda state: STATE_PRECEDENCE.index(state["state"]))
    return {"name": worst["name"], "state": worst["state"], "error": worst["error"]}


def aggregate_states(node_states: dict[str, dict]) -> dict[str, dict]:
    """Fold per-node states (see ``node_state``) into one state per identity."""
    grouped: dict[str, list[dict]] = {}
    for state in node_states.values():
        grouped.setdefault(state["identity"], []).append(state)
    return {identity: _fold(states) for identity, states in grouped.items()}


def _identity_kind(nodes: list[Any]) -> str:
    """Kind of one identity from its nodes (in node order).

    The primary node's kind unless it is ``other``; otherwise the first
    non-``other`` kind; otherwise ``other``.
    """
    primary = next((node for node in nodes if node.primary), None)
    if primary is not None and primary.kind != KIND_OTHER:
        return primary.kind
    return next((node.kind for node in nodes if node.kind != KIND_OTHER), KIND_OTHER)


def device_rows(entries: Iterable[Any], states: dict[str, dict]) -> list[dict]:
    """One listing row per identity: first node's path, name and vendor, keys on any node, every path.

    ``kind`` is folded over the nodes (see ``_identity_kind``); ``state``
    comes from ``states`` (per identity, see ``aggregate_states``).
    """
    rows: dict[str, dict] = {}
    nodes: dict[str, list] = {}
    for entry in entries:
        nodes.setdefault(entry.identity, []).append(entry)
        row = rows.get(entry.identity)
        if row is None:
            rows[entry.identity] = {"identity": entry.identity, "path": entry.path, "name": entry.name,
                                    "vendor": entry.vendor, "has_keys": entry.has_keys, "paths": [entry.path],
                                    "state": states.get(entry.identity, {}).get("state")}
            continue
        row["has_keys"] = row["has_keys"] or entry.has_keys
        row["paths"].append(entry.path)
    for identity, row in rows.items():
        row["kind"] = _identity_kind(nodes[identity])
    return list(rows.values())


def open_handle(entry: Any, open_device: Callable[[str], Any], selector: Any, data: Any) -> DeviceHandle:
    """Open ``entry``'s node (not grabbed) and register it for reading with ``data``."""
    device = open_device(entry.path)
    try:
        selector.register(device, selectors.EVENT_READ, data)
    except (OSError, ValueError):
        device.close()
        raise
    return DeviceHandle(entry.identity, entry.path, entry.name, device)


def close_handle(handle: DeviceHandle, selector: Any) -> None:
    """Stop the remapper (ungrab), unregister and close the node; never raises OSError."""
    if handle.remapper is not None:
        handle.remapper.stop()
    try:
        selector.unregister(handle.device)
    except (KeyError, ValueError, OSError) as exc:
        logger.debug("Unregister of %s failed: %s", handle.path, exc)
    try:
        handle.device.close()
    except OSError as exc:
        logger.warning("Closing %r failed: %s", handle.name, exc)


def attach_missing(entries: list, handles: dict[str, DeviceHandle], attach: Callable[[Any], Any]) -> None:
    """Attach every entry whose node is not open yet; failures are logged, not raised."""
    failures = []
    for entry in entries:
        if entry.path in handles:
            continue
        try:
            attach(entry)
        except OSError as exc:
            failures.append(f"{entry.path}: {exc}")
    if failures:
        logger.warning("Could not open %d node(s): %s", len(failures), "; ".join(failures))


def wanted_entries(configured: Iterable[Any], discover: Callable[[], Iterable[Any]]) -> list[tuple[Any, list]]:
    """``(node entry, enabled macros)`` for every discovered node of a device with enabled macros."""
    wanted = {device.identity: device.enabled_macros() for device in configured if device.enabled_macros()}
    if not wanted:
        return []  # nothing to remap: skip discovery
    return [(entry, wanted[entry.identity]) for entry in discover() if entry.identity in wanted]


def probe_nodes(handles: dict[str, DeviceHandle], identity: str, probe: Callable[[Any], bool]) -> tuple[int, int]:
    """``(probed, busy)`` over the open nodes of ``identity`` the engine does not grab itself."""
    probed = [handle for handle in handles.values() if handle.identity == identity
              and not (handle.remapper is not None and handle.remapper.active)]
    return len(probed), sum(1 for handle in probed if probe(handle.device))


def engine_grabs(handles: dict[str, DeviceHandle], identity: str) -> bool:
    """Whether the engine's own active remapper grabs any open node of ``identity``.

    Such a node is not probed but still delivers events to a recording, so the
    identity is never wholly blocked while it exists.
    """
    return any(handle.identity == identity and handle.remapper is not None and handle.remapper.active
               for handle in handles.values())


def paths_of(handles: dict[str, DeviceHandle], identity: str) -> list[str]:
    """Paths of the open nodes belonging to ``identity``."""
    return [path for path, handle in handles.items() if handle.identity == identity]
