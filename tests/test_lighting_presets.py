# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for built-in and user presets in the lighting panel (offscreen, pytest-qt)."""

import logging

import pytest

from hueberry.backend import animator, lighting_state, preset_store
from hueberry.backend.effects import EFFECT_BREATHE, EFFECT_WAVE, Preset
from hueberry.ui import worker
from hueberry.ui import lighting_panel
from hueberry.ui.lighting_panel import PRESET_DATA_PREFIX, PRESET_ERHEART, LightingPanel

MATRIX_CAPS = ("lighting", "lighting_static", "lighting_breath_dual", "lighting_led_matrix")
SERIAL = "KBD1"
SUNSET = Preset(key="sunset", label="Sunset", effect=EFFECT_WAVE,
                palette=((255, 80, 0), (120, 0, 200)))
OCEAN = Preset(key="ocean", label="Ocean", effect=EFFECT_BREATHE,
               palette=((0, 60, 255), (0, 200, 180)))
BROKEN_FILE = b"{ not json"


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
    """Keep presets.json inside the test's temporary directory."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def sync_worker(monkeypatch):
    """Make worker.run_async run synchronously."""
    monkeypatch.setattr(worker, "run_async", _run_sync)


@pytest.fixture
def passive_animator(monkeypatch):
    """Replace the shared animator with a thread-less one."""
    anim = animator.Animator(start_thread=False)
    monkeypatch.setattr(animator, "shared_animator", lambda: anim)
    state = lighting_state.LightingState(anim)
    monkeypatch.setattr(lighting_state, "shared_lighting_state", lambda: state)
    return anim


def _make_panel(qtbot, dev):
    panel = LightingPanel()
    qtbot.addWidget(panel)
    panel.set_device(dev)
    return panel


def _preset_items(panel):
    combo = panel.effect_combo
    items = [(combo.itemData(i), combo.itemText(i)) for i in range(combo.count())]
    return [(data, text) for data, text in items if data.startswith(PRESET_DATA_PREFIX)]


def _select(panel, data):
    index = panel.effect_combo.findData(data)
    assert index >= 0, data
    panel.effect_combo.setCurrentIndex(index)


def test_user_presets_listed_after_builtins(qtbot, make_device, passive_animator):
    preset_store.save([SUNSET])
    panel = _make_panel(qtbot, make_device(serial=SERIAL, capabilities=MATRIX_CAPS))
    assert _preset_items(panel) == [(PRESET_ERHEART, "Erheart"), ("preset:sunset", "Sunset")]
    first_preset = panel.effect_combo.findData(PRESET_ERHEART)
    assert all(not panel.effect_combo.itemData(i).startswith(PRESET_DATA_PREFIX)
               for i in range(first_preset))


def test_apply_user_preset_starts_animator(qtbot, make_device, passive_animator, sync_worker):
    preset_store.save([SUNSET])
    panel = _make_panel(qtbot, make_device(serial=SERIAL, capabilities=MATRIX_CAPS))
    _select(panel, "preset:sunset")
    assert panel.selected_preset() == SUNSET
    assert panel.preset_selected()
    messages = []
    panel.status.connect(messages.append)
    panel.apply_button.click()
    assert messages == ["Applied Sunset"]
    assert passive_animator.running_preset(SERIAL) == SUNSET.key


def test_plain_effect_is_not_a_preset(qtbot, make_device, passive_animator):
    panel = _make_panel(qtbot, make_device(serial=SERIAL, capabilities=MATRIX_CAPS))
    _select(panel, "static")
    assert panel.selected_preset() is None
    assert not panel.preset_selected()


def test_reload_picks_up_new_preset_and_keeps_selection(qtbot, make_device, passive_animator):
    preset_store.save([SUNSET])
    panel = _make_panel(qtbot, make_device(serial=SERIAL, capabilities=MATRIX_CAPS))
    _select(panel, "preset:sunset")
    preset_store.save([SUNSET, OCEAN])
    panel.reload_presets()
    assert ("preset:ocean", "Ocean") in _preset_items(panel)
    assert panel.selected_preset() == SUNSET
    assert panel.apply_button.isEnabled()


class _FailingState:
    """A lighting state whose stop_device always fails."""

    def stop_device(self, serial):
        raise RuntimeError(f"cannot stop {serial}")


def test_failed_stop_logs_serial_not_erheart(qtbot, make_device, passive_animator, sync_worker,
                                             monkeypatch, caplog):
    monkeypatch.setattr(lighting_state, "shared_lighting_state", _FailingState)
    dev = make_device(serial=SERIAL, capabilities=MATRIX_CAPS)
    panel = _make_panel(qtbot, dev)
    _select(panel, "static")
    with caplog.at_level(logging.ERROR, logger=lighting_panel.__name__):
        panel.apply_button.click()
    assert f"Could not stop the running preset on {SERIAL}" in caplog.text
    assert "Erheart" not in caplog.text


def test_load_error_reported_on_status(qtbot, make_device, passive_animator):
    panel = _make_panel(qtbot, make_device(serial=SERIAL, capabilities=MATRIX_CAPS))
    messages = []
    panel.status.connect(messages.append)
    path = preset_store.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(BROKEN_FILE)
    panel.reload_presets()
    assert len(messages) == 1 and messages[0]
    assert _preset_items(panel) == [(PRESET_ERHEART, "Erheart")]
