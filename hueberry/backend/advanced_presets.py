# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Advanced (per-key) presets: named groups of keys, each with its own effect.

An :class:`AdvancedPreset` holds one :class:`DeviceProgram` per device
(by serial); a program holds :class:`KeyGroup` s of matrix cells, and a cell
belongs to at most one group of its device. Everything is plain data saved
by :mod:`hueberry.backend.advanced_preset_store`. Nothing here imports
openrazer or Qt.
"""

from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from hueberry.backend.effects import KEY_PATTERN, PresetError
from hueberry.backend.key_effects import KeyEffect

__all__ = ["AdvancedPreset", "Cell", "DeviceProgram", "KeyGroup"]

Cell = tuple[int, int]
MAX_LABEL_LENGTH = 64
CELL_SIZE = 2  # a saved cell is [row, col]
MIN_INDEX = 0


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise PresetError(message)


def _check_label(label: Any, what: str) -> None:
    _check(isinstance(label, str) and bool(label.strip()), f"a {what} needs a name")
    _check(len(label) <= MAX_LABEL_LENGTH, f"{what} names are at most {MAX_LABEL_LENGTH} characters")


def _valid_cell(cell: Any) -> bool:
    return (isinstance(cell, tuple) and len(cell) == CELL_SIZE
            and all(isinstance(i, int) and not isinstance(i, bool) and i >= MIN_INDEX
                    for i in cell))


def _cell_from(data: Any) -> Cell:
    _check(isinstance(data, list) and len(data) == CELL_SIZE, "a key must be [row, col]")
    cell = (data[0], data[1])
    _check(_valid_cell(cell), f"invalid key position {data!r}")
    return cell


def _mapping(data: Any, what: str) -> Mapping[str, Any]:
    _check(isinstance(data, Mapping), f"a {what} must be an object")
    return data


def _list(data: Mapping[str, Any], name: str) -> list:
    value = data.get(name)
    _check(isinstance(value, list), f"{name!r} must be a list")
    return value


@dataclass(frozen=True)
class KeyGroup:
    """Named keys of one device sharing one effect."""

    name: str
    leds: tuple[Cell, ...] = ()
    effect: KeyEffect = field(default_factory=KeyEffect)

    def validate(self) -> None:
        """Raise PresetError describing the first problem."""
        _check_label(self.name, "key group")
        _check(isinstance(self.leds, tuple) and all(_valid_cell(c) for c in self.leds),
               f"group {self.name!r} has an invalid key position")
        _check(len(set(self.leds)) == len(self.leds), f"group {self.name!r} repeats a key")
        self.effect.validate()

    def with_changes(self, **changes: Any) -> "KeyGroup":
        """A copy with ``changes`` applied (not validated)."""
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready form; keys are ``[row, col]`` pairs."""
        return {"name": self.name, "leds": [list(cell) for cell in self.leds],
                "effect": self.effect.to_dict()}

    @classmethod
    def from_dict(cls, data: Any) -> "KeyGroup":
        """Build and validate a group from its saved form."""
        data = _mapping(data, "key group")
        group = cls(name=data.get("name"), leds=tuple(_cell_from(c) for c in _list(data, "leds")),
                    effect=KeyEffect.from_dict(_mapping(data.get("effect"), "key effect")))
        group.validate()
        return group


@dataclass(frozen=True)
class DeviceProgram:
    """The key groups of one device (``name`` is shown when it is absent)."""

    serial: str
    groups: tuple[KeyGroup, ...] = ()
    name: str = ""

    def validate(self) -> None:
        """Raise PresetError; a key may belong to only one group."""
        _check(isinstance(self.serial, str) and bool(self.serial), "a device needs a serial")
        _check(isinstance(self.name, str), "a device name must be text")
        _check(isinstance(self.groups, tuple), "groups must be a tuple")
        seen: set[Cell] = set()
        for group in self.groups:
            group.validate()
            overlap = sorted(seen.intersection(group.leds))
            if overlap:
                raise PresetError(f"key {overlap[0]} of {self.serial} is in two groups")
            seen.update(group.leds)

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready form."""
        return {"serial": self.serial, "name": self.name,
                "groups": [group.to_dict() for group in self.groups]}

    @classmethod
    def from_dict(cls, data: Any) -> "DeviceProgram":
        """Build and validate a program from its saved form."""
        data = _mapping(data, "device program")
        program = cls(serial=data.get("serial"), name=data.get("name", ""),
                      groups=tuple(KeyGroup.from_dict(g) for g in _list(data, "groups")))
        program.validate()
        return program


@dataclass(frozen=True)
class AdvancedPreset:
    """A named per-key preset over one or more devices."""

    key: str
    label: str
    programs: tuple[DeviceProgram, ...] = ()

    def validate(self) -> None:
        """Raise PresetError describing the first problem."""
        _check(isinstance(self.key, str) and bool(KEY_PATTERN.fullmatch(self.key)),
               f"invalid preset key {self.key!r}")
        _check_label(self.label, "preset")
        _check(isinstance(self.programs, tuple), "programs must be a tuple")
        serials = [program.serial for program in self.programs]
        _check(len(set(serials)) == len(serials), "a device appears twice in one preset")
        for program in self.programs:
            program.validate()

    def with_changes(self, **changes: Any) -> "AdvancedPreset":
        """A copy with ``changes`` applied (not validated)."""
        return replace(self, **changes)

    def program_for(self, serial: str) -> DeviceProgram | None:
        """The program of ``serial``, or None."""
        return next((p for p in self.programs if p.serial == serial), None)

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready form."""
        return {"key": self.key, "label": self.label,
                "programs": [program.to_dict() for program in self.programs]}

    @classmethod
    def from_dict(cls, data: Any) -> "AdvancedPreset":
        """Build and validate a preset from its saved form; PresetError when invalid."""
        data = _mapping(data, "preset")
        preset = cls(key=data.get("key"), label=data.get("label"),
                     programs=tuple(DeviceProgram.from_dict(p) for p in _list(data, "programs")))
        preset.validate()
        return preset
