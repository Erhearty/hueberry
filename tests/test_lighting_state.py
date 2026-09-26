# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for saving and restoring preset assignments (hueberry.backend.lighting_state)."""

import json
import logging
import stat

import pytest

from hueberry import config_files
from hueberry.backend import animator, lighting_state, preset_store, presets
from hueberry.backend.animator import Animator
from hueberry.backend.effects import EFFECT_BREATHE, EFFECT_WAVE, Preset
from hueberry.backend.lighting_state import MODE_GROUP, MODE_SINGLE, Assignment
from hueberry.ui import worker
from hueberry.ui.lighting_panel import PRESET_ERHEART, LightingPanel

MATRIX_CAPS = ("lighting", "lighting_static", "lighting_led_matrix")
ZONE_CAPS = ("lighting", "lighting_static")
KBD = "KBD0001"
MOUSE = "MOUSE0001"
PAD = "PAD0001"
FILE_MODE = 0o600
PHASE_STEPS = 3
BROKEN_FILE = b"{ not json"
SUNSET = Preset(key="sunset", label="Sunset", effect=EFFECT_WAVE,
                palette=((255, 80, 0), (120, 0, 200)))
OCEAN = Preset(key="ocean", label="Ocean", effect=EFFECT_BREATHE,
               palette=((0, 60, 255), (0, 200, 180)))
PRESETS = (SUNSET, OCEAN)


def _run_sync(fn, on_done=None, on_error=None):
    """Synchronous stand-in for worker.run_async."""
    try:
        result = fn()
    except Exception as exc:
        if on_error is not None:
            on_error(str(exc))
        return None
    if on_done is not None:
        on_done(result)
    return None


@pytest.fixture(autouse=True)
def config_home(monkeypatch, tmp_path):
    """Keep lighting_state.json inside the test's temporary directory."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def anim():
    return Animator(start_thread=False)


@pytest.fixture
def devices(make_device):
    return [make_device(name="Keyboard", serial=KBD, capabilities=MATRIX_CAPS),
            make_device(name="Mouse", serial=MOUSE, capabilities=ZONE_CAPS),
            make_device(name="Pad", serial=PAD, capabilities=MATRIX_CAPS)]


def _state(anim, known=PRESETS, error=None):
    return lighting_state.LightingState(anim, presets_provider=lambda: (list(known), error))


def _saved():
    return json.loads(lighting_state.config_path().read_text())


def _runs(anim):
    return sorted((run.preset.key, run.serials, run.grouped) for run in anim.runs())


def _apply_both(state, devices):
    kbd, mouse, pad = devices
    assert state.apply_single(kbd, SUNSET)
    assert state.apply_group([pad, mouse], OCEAN) == [PAD, MOUSE]


def test_round_trip_single_and_group(anim, devices):
    _apply_both(_state(anim), devices)
    path = lighting_state.config_path()
    assert stat.S_IMODE(path.stat().st_mode) == FILE_MODE
    assert _saved() == {"version": 1, "assignments": [
        {"preset_key": "sunset", "mode": "single", "serials": [KBD]},
        {"preset_key": "ocean", "mode": "group", "serials": [PAD, MOUSE]},
    ]}
    assert lighting_state.load() == ([Assignment("sunset", MODE_SINGLE, (KBD,)),
                                      Assignment("ocean", MODE_GROUP, (PAD, MOUSE))], None)


def test_device_belongs_to_one_assignment(anim, devices):
    state = _state(anim)
    _apply_both(state, devices)
    assert state.apply_single(devices[1], SUNSET)
    assert state.apply_single(devices[0], OCEAN)
    assert state.assignments() == [Assignment("ocean", MODE_GROUP, (PAD,)),
                                   Assignment("sunset", MODE_SINGLE, (MOUSE,)),
                                   Assignment("ocean", MODE_SINGLE, (KBD,))]


def test_restart_restores_same_runs(anim, devices):
    _apply_both(_state(anim), devices)
    before = _runs(anim)
    anim.shutdown()
    fresh = Animator(start_thread=False)
    assert _state(fresh).restore(devices) is None
    assert _runs(fresh) == before
    assert ("ocean", (PAD, MOUSE), True) in before


def test_missing_group_member_joins_later(anim, devices):
    kbd, mouse, pad = devices
    _state(anim).apply_group([pad, mouse], OCEAN)
    anim.shutdown()
    fresh = Animator(start_thread=False)
    state = _state(fresh)
    state.restore([kbd, mouse])
    assert _runs(fresh) == [("ocean", (MOUSE,), True)]
    assert state.assignments() == [Assignment("ocean", MODE_GROUP, (PAD, MOUSE))]
    state.restore(devices)
    assert _runs(fresh) == [("ocean", (PAD, MOUSE), True)]


def test_restore_is_idempotent(anim, devices):
    state = _state(anim)
    _apply_both(state, devices)
    for _ in range(PHASE_STEPS):
        anim.step()
    runs_before = list(anim._runs)
    phases = [run.phase for run in runs_before]
    assert any(phase != animator.START_PHASE for phase in phases)
    file_before = lighting_state.config_path().read_bytes()
    state.restore(devices)
    assert all(now is then for now, then in zip(anim._runs, runs_before, strict=True))
    assert [run.phase for run in anim._runs] == phases
    assert lighting_state.config_path().read_bytes() == file_before


def test_shutdown_and_lost_device_leave_file_alone(anim, devices):
    state = _state(anim)
    _apply_both(state, devices)
    path = lighting_state.config_path()
    before = path.read_bytes()
    anim.refresh(devices[:2])  # the pad is gone
    assert not anim.is_running(PAD)
    anim.shutdown()
    assert not anim.is_running()
    assert path.read_bytes() == before


def test_stop_device_clears_assignment(anim, devices):
    state = _state(anim)
    _apply_both(state, devices)
    assert state.stop_device(MOUSE)
    assert state.assignments() == [Assignment("sunset", MODE_SINGLE, (KBD,)),
                                   Assignment("ocean", MODE_GROUP, (PAD,))]
    state.stop_device(KBD)
    state.stop_device(PAD)
    assert _saved()["assignments"] == []
    assert not anim.is_running()


def test_panel_effect_clears_assignment(qtbot, monkeypatch, anim, devices):
    state = _state(anim)
    monkeypatch.setattr(worker, "run_async", _run_sync)
    monkeypatch.setattr(animator, "shared_animator", lambda: anim)
    monkeypatch.setattr(lighting_state, "shared_lighting_state", lambda: state)
    panel = LightingPanel()
    qtbot.addWidget(panel)
    panel.set_device(devices[0])
    panel.effect_combo.setCurrentIndex(panel.effect_combo.findData(PRESET_ERHEART))
    panel.apply_button.click()
    assert state.assignments() == [Assignment(presets.PRESET_KEY, MODE_SINGLE, (KBD,))]
    panel.effect_combo.setCurrentIndex(panel.effect_combo.findData("static"))
    panel.apply_button.click()
    assert state.assignments() == []
    assert _saved()["assignments"] == []
    assert not anim.is_running(KBD)


def test_forget_preset_drops_its_assignments(anim, devices):
    kbd, mouse, pad = devices
    state = _state(anim)
    state.apply_single(kbd, OCEAN)
    state.apply_group([pad, mouse], SUNSET)
    assert state.forget_preset(SUNSET.key) == 1
    assert state.assignments() == [Assignment("ocean", MODE_SINGLE, (KBD,))]
    assert _saved()["assignments"] == [{"preset_key": "ocean", "mode": "single",
                                        "serials": [KBD]}]
    assert anim.running_preset(PAD) is None and anim.running_preset(MOUSE) is None
    assert anim.running_preset(KBD) == OCEAN.key


@pytest.mark.parametrize("content", [
    BROKEN_FILE,
    json.dumps({"version": 1, "assignments": [
        {"preset_key": "ocean", "mode": "single", "serials": [KBD, PAD]}]}).encode(),
])
def test_corrupt_file_is_quarantined(anim, devices, content):
    path = lighting_state.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    state = _state(anim)
    error = state.restore(devices)
    assert error and ".bak" in error
    assert not path.exists()
    assert path.with_name(path.name + ".bak").read_bytes() == content
    assert state.assignments() == []
    assert state.restore(devices) is None  # reported once


def test_unknown_preset_dropped_with_warning(anim, devices, caplog):
    _apply_both(_state(anim), devices)
    anim.shutdown()
    fresh = Animator(start_thread=False)
    state = _state(fresh, known=(OCEAN,))
    with caplog.at_level(logging.WARNING, logger=lighting_state.__name__):
        state.restore(devices)
    assert "'sunset' no longer exists" in caplog.text
    assert state.assignments() == [Assignment("ocean", MODE_GROUP, (PAD, MOUSE))]
    assert [entry["preset_key"] for entry in _saved()["assignments"]] == ["ocean"]
    assert _runs(fresh) == [("ocean", (PAD, MOUSE), True)]


def test_unsaved_running_preset_survives_restore(anim, devices):
    state = _state(anim, known=())
    assert state.apply_single(devices[0], SUNSET)
    state.restore(devices)
    assert state.assignments() == [Assignment("sunset", MODE_SINGLE, (KBD,))]
    assert [entry["preset_key"] for entry in _saved()["assignments"]] == ["sunset"]
    assert anim.running_preset(KBD) == SUNSET.key
    preset_store.save([SUNSET])
    anim.shutdown()
    fresh = Animator(start_thread=False)
    lighting_state.LightingState(fresh).restore(devices)
    assert fresh.running_preset(KBD) == SUNSET.key


def test_preset_error_keeps_assignments_and_starts_known(anim, devices):
    _apply_both(_state(anim), devices)
    anim.shutdown()
    before = lighting_state.config_path().read_bytes()
    fresh = Animator(start_thread=False)
    state = _state(fresh, known=(OCEAN,), error="boom")
    state.restore(devices)
    assert len(state.assignments()) == 2
    assert lighting_state.config_path().read_bytes() == before
    assert _runs(fresh) == [("ocean", (PAD, MOUSE), True)]


def test_default_provider_load_error_keeps_assignments(anim, devices, monkeypatch):
    _apply_both(_state(anim), devices)
    anim.shutdown()
    before = lighting_state.config_path().read_bytes()
    monkeypatch.setattr(preset_store, "load", lambda path=None: ([], "boom"))
    state = lighting_state.LightingState(Animator(start_thread=False))
    state.restore(devices)
    assert len(state.assignments()) == 2
    assert lighting_state.config_path().read_bytes() == before


def test_save_error_is_raised_after_the_change(anim, devices, monkeypatch):
    def fail(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(config_files, "atomic_write", fail)
    state = _state(anim)
    with pytest.raises(OSError, match="disk full"):
        state.apply_single(devices[0], SUNSET)
    assert anim.running_preset(KBD) == SUNSET.key
    assert state.assignments() == [Assignment("sunset", MODE_SINGLE, (KBD,))]


def test_shared_lighting_state_is_a_singleton(anim, monkeypatch):
    monkeypatch.setattr(animator, "shared_animator", lambda: anim)
    assert lighting_state.shared_lighting_state() is lighting_state.shared_lighting_state()
