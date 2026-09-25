# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Macro data model: steps, macros, per-device macro sets and validation.

The model is deliberately closed: only key and delay steps exist, so a macro
file can never make the engine run programs (``shell`` steps are rejected on
load, not merely ignored). Limits bound how long a macro can keep synthetic
input flowing and how much a hostile or corrupt file can make us allocate.
"""

from dataclasses import dataclass, field
from typing import Any

from hueberry.macros import keycodes

MAX_DELAY_MS = 10_000
MIN_DELAY_MS = 0
MAX_STEPS = 500
MAX_NAME_LENGTH = 100
MAX_ID_LENGTH = 64
STEP_KEY = "key"
STEP_DELAY = "delay"
ACTION_PRESS = "press"
ACTION_RELEASE = "release"
ACTION_TAP = "tap"
ACTIONS = (ACTION_PRESS, ACTION_RELEASE, ACTION_TAP)


class ModelError(ValueError):
    """Macro data that is malformed or violates a limit."""


def _field(data: Any, key: str, kind: type) -> Any:
    """Fetch ``data[key]`` insisting on ``kind`` (bools are not ints here)."""
    if not isinstance(data, dict):
        raise ModelError(f"expected an object holding {key!r}")
    value = data.get(key)
    if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
        raise ModelError(f"{key!r} must be {kind.__name__}, got {type(value).__name__}")
    return value


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


Step = KeyStep | DelayStep


def step_from_dict(data: Any) -> Step:
    """Parse one step; any type other than key/delay (e.g. ``shell``) is refused."""
    kind = data.get("type") if isinstance(data, dict) else None
    if kind == STEP_KEY:
        return KeyStep(_field(data, "code", str), _field(data, "action", str))
    if kind == STEP_DELAY:
        return DelayStep(_field(data, "ms", int))
    raise ModelError(f"unsupported step type: {kind!r}")


@dataclass
class Macro:
    """A named step sequence bound to one trigger key/button of a device."""

    id: str
    name: str
    enabled: bool
    trigger: str
    steps: list = field(default_factory=list)

    def to_dict(self) -> dict:
        """JSON-ready form."""
        return {
            "id": self.id, "name": self.name, "enabled": self.enabled,
            "trigger": self.trigger, "steps": [step.to_dict() for step in self.steps],
        }

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
        )

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
        for step in self.steps:
            if not isinstance(step, (KeyStep, DelayStep)):
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
        """Parse the configuration; raises ModelError on wrong shapes."""
        return cls(devices=[DeviceMacros.from_dict(item) for item in _field(data, "devices", list)])

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
