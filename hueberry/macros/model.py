# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Macro data model: steps, macros, per-device macro sets and validation.

The model is deliberately closed: only key, delay and allow-listed app-action
steps exist (an app step can only name an action from ``gui_link.APP_ACTIONS``),
so a macro file can never make the engine run programs (``shell`` steps are
still rejected on load, not merely ignored). Limits bound how long a macro can keep synthetic
input flowing and how much a hostile or corrupt file can make us allocate.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from hueberry import gui_link
from hueberry.macros import keycodes

MAX_DELAY_MS = 10_000
MIN_DELAY_MS = 0
MAX_STEPS = 500
MAX_NAME_LENGTH = 100
MAX_ID_LENGTH = 64
STEP_KEY = "key"
STEP_DELAY = "delay"
STEP_APP = "app"
ACTION_PRESS = "press"
ACTION_RELEASE = "release"
ACTION_TAP = "tap"
ACTIONS = (ACTION_PRESS, ACTION_RELEASE, ACTION_TAP)
REPEAT_ONCE = "once"
REPEAT_TIMES = "times"
REPEAT_TOGGLE = "toggle"  # loop until the trigger is pressed again
REPEAT_MODES = (REPEAT_ONCE, REPEAT_TIMES, REPEAT_TOGGLE)
MIN_REPEAT_COUNT = 1
MAX_REPEAT_COUNT = 1000
INPUT_NODE_SUFFIX_RE = re.compile(r"/input\d+$")  # per-interface part of a USB phys path

logger = logging.getLogger(__name__)


class ModelError(ValueError):
    """Macro data that is malformed or violates a limit."""


def canonical_identity(identity: str) -> str:
    """One identity per physical device: drop a trailing ``/input<N>``.

    A USB device exposes one evdev node per interface (``.../input0``,
    ``.../input1``, ...); they are the same physical device, so macros and
    recordings address them together. Idempotent.
    """
    return INPUT_NODE_SUFFIX_RE.sub("", identity, count=1)


def _field(data: Any, key: str, kind: type) -> Any:
    """Fetch ``data[key]`` insisting on ``kind`` (bools are not ints here)."""
    if not isinstance(data, dict):
        raise ModelError(f"expected an object holding {key!r}")
    value = data.get(key)
    if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
        raise ModelError(f"{key!r} must be {kind.__name__}, got {type(value).__name__}")
    return value


def _optional(data: Any, key: str, kind: type, default: Any) -> Any:
    """Like ``_field`` but a missing ``key`` yields ``default`` (older files lack it).

    A present value of the wrong type still raises ModelError; bools are not ints.
    """
    if not isinstance(data, dict):
        raise ModelError(f"expected an object holding {key!r}")
    if key not in data:
        return default
    return _field(data, key, kind)


@dataclass(frozen=True)
class KeyStep:
    """Press, release or tap (press then release) one key or button by evdev name."""

    code: str
    action: str = ACTION_TAP

    def to_dict(self) -> dict:
        """JSON-ready form."""
        return {"type": STEP_KEY, "code": self.code, "action": self.action}

    def problems(self) -> list[str]:
        """Human-readable reasons this step is invalid ([] when valid)."""
        found = []
        if not keycodes.is_valid_code(self.code):
            found.append(f"unknown key code {self.code!r}")
        if self.action not in ACTIONS:
            found.append(f"unknown key action {self.action!r}")
        return found


@dataclass(frozen=True)
class DelayStep:
    """Wait ``ms`` milliseconds between steps."""

    ms: int

    def to_dict(self) -> dict:
        """JSON-ready form."""
        return {"type": STEP_DELAY, "ms": self.ms}

    def problems(self) -> list[str]:
        """Human-readable reasons this step is invalid ([] when valid)."""
        if not MIN_DELAY_MS <= self.ms <= MAX_DELAY_MS:
            return [f"delay {self.ms} ms outside {MIN_DELAY_MS}..{MAX_DELAY_MS}"]
        return []


@dataclass(frozen=True)
class AppActionStep:
    """Ask the running Hueberry window to perform one allow-listed app action."""

    action: str

    def to_dict(self) -> dict:
        """JSON-ready form."""
        return {"type": STEP_APP, "action": self.action}

    def problems(self) -> list[str]:
        """Human-readable reasons this step is invalid ([] when valid)."""
        if self.action not in gui_link.APP_ACTIONS:
            return [f"unknown app action {self.action!r}"]
        return []


Step = KeyStep | DelayStep | AppActionStep
STEP_CLASSES = (KeyStep, DelayStep, AppActionStep)


def step_from_dict(data: Any) -> Step:
    """Parse one step; any type other than key/delay/app (e.g. ``shell``) is refused."""
    kind = data.get("type") if isinstance(data, dict) else None
    if kind == STEP_KEY:
        return KeyStep(_field(data, "code", str), _field(data, "action", str))
    if kind == STEP_DELAY:
        return DelayStep(_field(data, "ms", int))
    if kind == STEP_APP:
        return AppActionStep(_field(data, "action", str))
    raise ModelError(f"unsupported step type: {kind!r}")


@dataclass
class Macro:
    """A named step sequence bound to one trigger key/button of a device."""

    id: str
    name: str
    enabled: bool
    trigger: str
    steps: list = field(default_factory=list)
    repeat_mode: str = REPEAT_ONCE
    repeat_count: int = 1

    def to_dict(self) -> dict:
        """JSON-ready form."""
        return {
            "id": self.id, "name": self.name, "enabled": self.enabled,
            "trigger": self.trigger, "steps": [step.to_dict() for step in self.steps],
            "repeat_mode": self.repeat_mode, "repeat_count": self.repeat_count,
        }

    def iterations(self) -> int | None:
        """How often the steps run per trigger press: 1, ``repeat_count``, or None (until stopped)."""
        if self.repeat_mode == REPEAT_TOGGLE:
            return None
        if self.repeat_mode == REPEAT_TIMES:
            return self.repeat_count
        return 1

    @classmethod
    def from_dict(cls, data: Any) -> "Macro":
        """Parse a macro; raises ModelError on wrong shapes or step types."""
        steps = _field(data, "steps", list)
        if len(steps) > MAX_STEPS:  # refuse before building huge lists
            raise ModelError(f"macro has {len(steps)} steps, limit is {MAX_STEPS}")
        return cls(
            id=_field(data, "id", str), name=_field(data, "name", str),
            enabled=_field(data, "enabled", bool), trigger=_field(data, "trigger", str),
            steps=[step_from_dict(step) for step in steps],
            repeat_mode=_optional(data, "repeat_mode", str, REPEAT_ONCE),
            repeat_count=_optional(data, "repeat_count", int, 1),
        )

    def _repeat_problems(self) -> list[str]:
        """Unknown repeat mode, or a count outside the range for REPEAT_TIMES."""
        if self.repeat_mode not in REPEAT_MODES:
            return [f"unknown repeat mode {self.repeat_mode!r}"]
        count = self.repeat_count
        if self.repeat_mode == REPEAT_TIMES and (
                not isinstance(count, int) or isinstance(count, bool)
                or not MIN_REPEAT_COUNT <= count <= MAX_REPEAT_COUNT):
            return [f"repeat count {count!r} outside {MIN_REPEAT_COUNT}..{MAX_REPEAT_COUNT}"]
        return []

    def problems(self) -> list[str]:
        """Human-readable reasons this macro is invalid ([] when valid)."""
        found = []
        if not self.id or len(self.id) > MAX_ID_LENGTH:
            found.append(f"macro id must be 1..{MAX_ID_LENGTH} characters")
        if len(self.name) > MAX_NAME_LENGTH:
            found.append(f"macro name longer than {MAX_NAME_LENGTH} characters")
        if not keycodes.is_valid_code(self.trigger):
            found.append(f"unknown trigger {self.trigger!r}")
        if len(self.steps) > MAX_STEPS:
            found.append(f"{len(self.steps)} steps, limit is {MAX_STEPS}")
        found.extend(self._repeat_problems())
        if self.repeat_mode == REPEAT_TOGGLE and any(isinstance(step, AppActionStep) for step in self.steps):
            found.append("app-action steps cannot loop in toggle mode (would flood the window)")
        for step in self.steps:
            if not isinstance(step, STEP_CLASSES):
                found.append(f"unsupported step {step!r}")
                continue
            found.extend(step.problems())
        return [f"macro {self.name or self.id!r}: {problem}" for problem in found]


def _duplicates(values: list[str]) -> set[str]:
    seen: set[str] = set()
    return {value for value in values if value in seen or seen.add(value)}


@dataclass
class DeviceMacros:
    """All macros of one physical device, keyed by its engine identity string."""

    identity: str
    name: str = ""
    macros: list = field(default_factory=list)

    def enabled_macros(self) -> list[Macro]:
        """Macros that should currently fire."""
        return [macro for macro in self.macros if macro.enabled]

    def to_dict(self) -> dict:
        """JSON-ready form."""
        return {"identity": self.identity, "name": self.name,
                "macros": [macro.to_dict() for macro in self.macros]}

    @classmethod
    def from_dict(cls, data: Any) -> "DeviceMacros":
        """Parse a device entry; raises ModelError on wrong shapes."""
        return cls(identity=_field(data, "identity", str), name=_field(data, "name", str),
                   macros=[Macro.from_dict(item) for item in _field(data, "macros", list)])

    def problems(self) -> list[str]:
        """Macro problems plus duplicate ids/triggers (one trigger, one macro)."""
        found = [problem for macro in self.macros for problem in macro.problems()]
        for trigger in sorted(_duplicates([macro.trigger for macro in self.macros])):
            found.append(f"trigger {trigger} is bound to more than one macro")
        for macro_id in sorted(_duplicates([macro.id for macro in self.macros])):
            found.append(f"macro id {macro_id!r} is used more than once")
        return [f"device {self.name or self.identity!r}: {problem}" for problem in found]


def _merge_into(existing: DeviceMacros, device: DeviceMacros) -> None:
    """Append ``device``'s macros to ``existing`` (same canonical identity).

    A macro whose trigger or id ``existing`` already holds is skipped with a
    warning; the check is against ``existing`` as it was before this merge, so
    duplicates inside ``device`` itself are kept and reported by ``problems()``.
    The first non-empty name wins.
    """
    triggers = {macro.trigger for macro in existing.macros}
    ids = {macro.id for macro in existing.macros}
    for macro in device.macros:
        if macro.trigger in triggers or macro.id in ids:
            logger.warning("Merging %r: skipped macro %r (trigger %r), trigger or id already bound",
                           existing.identity, macro.id, macro.trigger)
            continue
        existing.macros.append(macro)
    existing.name = existing.name or device.name


@dataclass
class MacroConfig:
    """The whole macro configuration, as stored in macros.json."""

    devices: list = field(default_factory=list)

    def for_device(self, identity: str) -> DeviceMacros | None:
        """The macro set for ``identity``, or None."""
        return next((device for device in self.devices if device.identity == identity), None)

    def to_dict(self) -> dict:
        """JSON-ready form (the store adds the schema version)."""
        return {"devices": [device.to_dict() for device in self.devices]}

    @classmethod
    def from_dict(cls, data: Any) -> "MacroConfig":
        """Parse the configuration; raises ModelError on wrong shapes.

        Identities are canonicalised and entries that then collide (older files
        keyed per ``/input<N>`` node) are merged (see ``_merge_into``): macros
        concatenated in order, a later entry's macro skipped with a warning when
        its trigger or id is already taken, first non-empty name kept. So one
        conflicting old entry cannot invalidate the whole file; duplicates within
        a single entry still surface through ``problems()``. Idempotent.
        """
        merged: dict[str, DeviceMacros] = {}
        for item in _field(data, "devices", list):
            device = DeviceMacros.from_dict(item)
            device.identity = canonical_identity(device.identity)
            existing = merged.get(device.identity)
            if existing is None:
                merged[device.identity] = device
                continue
            _merge_into(existing, device)
        return cls(devices=list(merged.values()))

    def problems(self) -> list[str]:
        """Every validation problem across devices ([] when valid)."""
        found = [problem for device in self.devices for problem in device.problems()]
        for identity in sorted(_duplicates([device.identity for device in self.devices])):
            found.append(f"device {identity!r} is listed more than once")
        return found

    def validate(self) -> None:
        """Raise ModelError listing every problem, so nothing invalid is saved or run."""
        found = self.problems()
        if found:
            raise ModelError("; ".join(found))
