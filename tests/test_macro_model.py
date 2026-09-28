# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the macro model, validation and key-name helpers."""

import json
import sys

import pytest

from hueberry import gui_link
from hueberry.macros import keycodes
from hueberry.macros.model import (
    MAX_DELAY_MS,
    MAX_REPEAT_COUNT,
    MAX_STEPS,
    MIN_REPEAT_COUNT,
    REPEAT_ONCE,
    REPEAT_TIMES,
    REPEAT_TOGGLE,
    AppActionStep,
    DelayStep,
    DeviceMacros,
    KeyStep,
    Macro,
    MacroConfig,
    ModelError,
    canonical_identity,
    step_from_dict,
)

IDENTITY = "1532:0084:Razer Mouse:usb-1"


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


def test_app_step_round_trips():
    """An allow-listed app step survives to_dict -> JSON -> from_dict and validates."""
    step = AppActionStep(gui_link.APP_ACTION_TOGGLE_SYSMON)
    assert step.to_dict() == {"type": "app", "action": "toggle-sysmon"}
    macro = _macro(steps=[KeyStep("KEY_A"), step])
    restored = Macro.from_dict(json.loads(json.dumps(macro.to_dict())))
    assert restored == macro and restored.steps[1] == step
    assert not _config(restored).problems()


def test_unknown_app_action_is_rejected():
    """An action outside APP_ACTIONS is a validation problem; a wrong type is refused on load."""
    config = _config(_macro(steps=[step_from_dict({"type": "app", "action": "launch-shell"})]))
    assert "launch-shell" in " ".join(config.problems())
    with pytest.raises(ModelError):
        config.validate()
    with pytest.raises(ModelError):
        step_from_dict({"type": "app", "action": 1})
    with pytest.raises(ModelError):
        step_from_dict({"type": "app"})


def test_toggle_macro_with_app_step_is_flagged():
    """A looping (toggle) macro may not contain an app step; once/times may."""
    macro = _macro(steps=[AppActionStep(gui_link.APP_ACTION_TOGGLE_SYSMON)])
    macro.repeat_mode = REPEAT_TOGGLE
    assert "toggle" in " ".join(_config(macro).problems())
    macro.repeat_mode, macro.repeat_count = REPEAT_TIMES, 2
    assert not _config(macro).problems()


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


def test_canonical_identity_strips_one_input_suffix():
    """Only a single trailing /input<digits> goes; the result is stable."""
    assert canonical_identity(IDENTITY + "/input0") == IDENTITY
    assert canonical_identity(IDENTITY + "/input12") == IDENTITY
    assert canonical_identity(IDENTITY) == IDENTITY
    assert canonical_identity("a:b:SN/input1/input2") == "a:b:SN/input1"
    assert canonical_identity("a:b:usb-1/input0x") == "a:b:usb-1/input0x"
    assert canonical_identity(canonical_identity(IDENTITY + "/input3")) == IDENTITY


def test_old_per_node_entries_are_merged_on_load():
    """Entries for /input0 and /input1 load as one device; macros concatenated, first name kept."""
    first, second = _macro("m1", "BTN_SIDE"), _macro("m2", "BTN_EXTRA")
    data = {"devices": [
        DeviceMacros(IDENTITY + "/input0", "", [first]).to_dict(),
        DeviceMacros(IDENTITY + "/input1", "Razer Mouse", [second]).to_dict(),
        DeviceMacros(IDENTITY + "/input2", "Other name", []).to_dict(),
    ]}
    config = MacroConfig.from_dict(data)
    assert config == MacroConfig([DeviceMacros(IDENTITY, "Razer Mouse", [first, second])])
    config.validate()
    assert MacroConfig.from_dict(config.to_dict()) == config


def test_merge_conflicts_keep_the_first_macro(caplog):
    """A trigger bound on two old nodes: the first macro is kept, the other skipped with a warning."""
    first, clash, other = _macro("m1", "BTN_SIDE"), _macro("m2", "BTN_SIDE"), _macro("m3", "BTN_EXTRA")
    data = {"devices": [
        DeviceMacros(IDENTITY + "/input0", "Razer Mouse", [first]).to_dict(),
        DeviceMacros(IDENTITY + "/input1", "Razer Mouse", [clash, other]).to_dict(),
    ]}
    with caplog.at_level("WARNING", logger="hueberry.macros.model"):
        config = MacroConfig.from_dict(data)
    assert config == MacroConfig([DeviceMacros(IDENTITY, "Razer Mouse", [first, other])])
    assert config.problems() == []
    (record,) = caplog.records
    assert record.levelname == "WARNING" and IDENTITY in record.getMessage()
    assert "'m2'" in record.getMessage() and "BTN_SIDE" in record.getMessage()
    assert MacroConfig.from_dict(config.to_dict()) == config


def test_duplicate_trigger_within_one_entry_still_surfaces():
    """Duplicates inside a single entry are not merged away: validation still reports them."""
    entry = DeviceMacros(IDENTITY + "/input0", "Razer Mouse", [_macro("m1", "BTN_SIDE"), _macro("m2", "BTN_SIDE")])
    config = MacroConfig.from_dict({"devices": [entry.to_dict()]})
    assert "BTN_SIDE" in " ".join(config.problems())
    with pytest.raises(ModelError):
        config.validate()


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


def test_repeat_fields_default_when_absent():
    """An old macro dict without repeat keys loads as once / count 1."""
    data = _macro().to_dict()
    del data["repeat_mode"], data["repeat_count"]
    macro = Macro.from_dict(data)
    assert (macro.repeat_mode, macro.repeat_count) == (REPEAT_ONCE, 1)
    assert macro == _macro()


@pytest.mark.parametrize("mode, count", [(REPEAT_ONCE, 1), (REPEAT_TIMES, 7), (REPEAT_TOGGLE, 1)])
def test_repeat_fields_round_trip(mode, count):
    """Every repeat mode survives to_dict -> JSON -> from_dict and validates."""
    macro = _macro()
    macro.repeat_mode, macro.repeat_count = mode, count
    restored = Macro.from_dict(json.loads(json.dumps(macro.to_dict())))
    assert restored == macro and restored.to_dict()["repeat_mode"] == mode
    assert not _config(restored).problems()


@pytest.mark.parametrize("mode, count, needle", [
    ("forever", 1, "forever"),
    (REPEAT_TIMES, MIN_REPEAT_COUNT - 1, "repeat count"),
    (REPEAT_TIMES, MAX_REPEAT_COUNT + 1, "repeat count"),
])
def test_invalid_repeat_is_reported(mode, count, needle):
    """An unknown mode, or a times count outside MIN..MAX, is a validation problem."""
    macro = _macro()
    macro.repeat_mode, macro.repeat_count = mode, count
    assert needle in " ".join(_config(macro).problems())
    with pytest.raises(ModelError):
        _config(macro).validate()


def test_repeat_count_bounds_are_valid():
    """MIN and MAX counts themselves are accepted for times."""
    for count in (MIN_REPEAT_COUNT, MAX_REPEAT_COUNT):
        macro = _macro()
        macro.repeat_mode, macro.repeat_count = REPEAT_TIMES, count
        assert not _config(macro).problems()


@pytest.mark.parametrize("key, value", [("repeat_count", True), ("repeat_count", "3"), ("repeat_mode", 1)])
def test_repeat_fields_wrong_type_rejected(key, value):
    """A bool (or other wrong type) for a repeat field is refused on load."""
    data = _macro().to_dict()
    data[key] = value
    with pytest.raises(ModelError, match=key):
        Macro.from_dict(data)


def test_iterations_per_mode():
    """once -> 1, times -> repeat_count, toggle -> None (until stopped)."""
    macro = _macro()
    assert macro.iterations() == 1
    macro.repeat_mode, macro.repeat_count = REPEAT_TIMES, 5
    assert macro.iterations() == 5
    macro.repeat_mode = REPEAT_TOGGLE
    assert macro.iterations() is None
    macro.repeat_mode, macro.repeat_count = REPEAT_ONCE, 9
    assert macro.iterations() == 1


def test_events_to_steps_custom_gap_and_cap():
    """min_gap_ms is honoured and output never exceeds MAX_STEPS."""
    recorded = [("KEY_A", 1, 0.0), ("KEY_A", 0, 0.004)]
    assert keycodes.events_to_steps(recorded, min_gap_ms=3) == [
        KeyStep("KEY_A", "press"), DelayStep(4), KeyStep("KEY_A", "release"),
    ]
    many = [("KEY_A", index % 2, index * 0.01) for index in range(MAX_STEPS)]
    assert len(keycodes.events_to_steps(many)) == MAX_STEPS
