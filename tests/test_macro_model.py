# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the macro model, validation and key-name helpers."""

import json
import sys

import pytest

from hueberry.macros import keycodes
from hueberry.macros.model import (
    MAX_DELAY_MS,
    MAX_STEPS,
    DelayStep,
    DeviceMacros,
    KeyStep,
    Macro,
    MacroConfig,
    ModelError,
    step_from_dict,
)

IDENTITY = "1532:0084:Razer Mouse:usb-1/input0"


def _macro(macro_id="m1", trigger="BTN_SIDE", steps=None, enabled=True):
    steps = steps if steps is not None else [KeyStep("KEY_A"), DelayStep(20), KeyStep("KEY_B", "press")]
    return Macro(id=macro_id, name=f"Macro {macro_id}", enabled=enabled, trigger=trigger, steps=steps)


def _config(*macros):
    return MacroConfig(devices=[DeviceMacros(IDENTITY, "Razer Mouse", list(macros))])


def test_valid_config_round_trips_through_json():
    """to_dict -> JSON -> from_dict yields an equal, valid config."""
    config = _config(_macro(), _macro("m2", "BTN_EXTRA", enabled=False))
    config.validate()
    restored = MacroConfig.from_dict(json.loads(json.dumps(config.to_dict())))
    assert restored == config
    assert restored.for_device(IDENTITY).enabled_macros() == [config.devices[0].macros[0]]
    assert restored.for_device("other") is None


@pytest.mark.parametrize("step", [
    {"type": "shell", "command": "rm -rf ~"},
    {"type": "exec"},
    {"code": "KEY_A"},
    "KEY_A",
    {"type": "delay", "ms": "10"},
    {"type": "delay", "ms": True},
    {"type": "key", "code": 30, "action": "tap"},
])
def test_step_from_dict_rejects_unknown_or_malformed(step):
    """Shell/unknown step types and wrongly typed fields are refused."""
    with pytest.raises(ModelError):
        step_from_dict(step)


def test_macro_from_dict_rejects_shell_step():
    """A macro containing a shell step cannot be loaded at all."""
    data = _macro().to_dict()
    data["steps"].append({"type": "shell", "command": "echo hi"})
    with pytest.raises(ModelError, match="shell"):
        Macro.from_dict(data)


def test_bad_codes_are_reported():
    """Unknown trigger or step codes, and bad actions, are validation problems."""
    config = _config(_macro(trigger="KEY_NOPE", steps=[KeyStep("NOT_A_KEY"), KeyStep("KEY_A", "hold")]))
    problems = " ".join(config.problems())
    assert "KEY_NOPE" in problems and "NOT_A_KEY" in problems and "hold" in problems
    with pytest.raises(ModelError):
        config.validate()


@pytest.mark.parametrize("ms, valid", [(0, True), (MAX_DELAY_MS, True), (-1, False), (MAX_DELAY_MS + 1, False)])
def test_delay_bounds(ms, valid):
    """Delays must lie within 0..MAX_DELAY_MS."""
    assert (not _config(_macro(steps=[DelayStep(ms)])).problems()) is valid


def test_step_limit():
    """More than MAX_STEPS steps is invalid, and refused on load."""
    steps = [KeyStep("KEY_A")] * (MAX_STEPS + 1)
    assert _config(_macro(steps=steps)).problems()
    assert not _config(_macro(steps=steps[:MAX_STEPS])).problems()
    with pytest.raises(ModelError):
        Macro.from_dict(_macro(steps=steps).to_dict())


def test_duplicate_triggers_and_ids_are_rejected():
    """One trigger per device; ids unique; identities unique."""
    config = _config(_macro("m1", "BTN_SIDE"), _macro("m2", "BTN_SIDE", enabled=False))
    assert any("BTN_SIDE" in problem for problem in config.problems())
    assert _config(_macro("m1"), _macro("m1", "BTN_EXTRA")).problems()
    doubled = MacroConfig(devices=[DeviceMacros(IDENTITY), DeviceMacros(IDENTITY)])
    assert doubled.problems()


def test_empty_id_is_rejected():
    """Macros need an id."""
    assert _config(_macro(macro_id="")).problems()


def test_key_name_helpers():
    """Names validate against ecodes; lists contain only KEY_/BTN_ names."""
    assert keycodes.is_valid_code("KEY_A") and keycodes.is_valid_code("BTN_LEFT")
    assert not keycodes.is_valid_code("EV_KEY")
    assert not keycodes.is_valid_code("KEY_RESERVED")
    assert not keycodes.is_valid_code(30)
    names = keycodes.all_key_names()
    assert "KEY_A" in names and "BTN_SIDE" in names
    assert all(name.startswith(("KEY_", "BTN_")) for name in names)
    assert "KEY_MAX" not in names and "KEY_CNT" not in names
    assert keycodes.code_for("KEY_A") == 30
    assert keycodes.name_for(0x110) == "BTN_LEFT"
    assert keycodes.display_name("BTN_SIDE") == "Button Side"
    assert keycodes.display_name("KEY_A") == "A"


def test_key_names_without_evdev(monkeypatch):
    """Without python-evdev names are checked by shape and lists are empty."""
    monkeypatch.setitem(sys.modules, "evdev", None)
    assert keycodes.is_valid_code("KEY_A")
    assert not keycodes.is_valid_code("KEY_a b")
    assert keycodes.all_key_names() == []
    assert keycodes.code_for("KEY_A") is None


def test_events_to_steps_collapses_small_gaps():
    """Gaps below min_gap_ms vanish; larger ones become (clamped) delays; repeats skip."""
    recorded = [
        ("KEY_A", 1, 10.000),
        ("KEY_A", 2, 10.050),
        ("KEY_A", 0, 10.002),
        ("KEY_B", 1, 10.102),
        ("KEY_B", 0, 30.102),
        ("KEY_NOPE", 1, 30.2),
    ]
    assert keycodes.events_to_steps(recorded) == [
        KeyStep("KEY_A", "press"),
        KeyStep("KEY_A", "release"),
        DelayStep(100),
        KeyStep("KEY_B", "press"),
        DelayStep(MAX_DELAY_MS),
        KeyStep("KEY_B", "release"),
    ]


def test_events_to_steps_custom_gap_and_cap():
    """min_gap_ms is honoured and output never exceeds MAX_STEPS."""
    recorded = [("KEY_A", 1, 0.0), ("KEY_A", 0, 0.004)]
    assert keycodes.events_to_steps(recorded, min_gap_ms=3) == [
        KeyStep("KEY_A", "press"), DelayStep(4), KeyStep("KEY_A", "release"),
    ]
    many = [("KEY_A", index % 2, index * 0.01) for index in range(MAX_STEPS)]
    assert len(keycodes.events_to_steps(many)) == MAX_STEPS
