# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the PyQt6 panels (run offscreen with pytest-qt)."""

from pathlib import Path

import pytest
from PyQt6 import sip
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QAbstractSlider, QWidget

from hueberry.backend import animator
from hueberry.backend.daemon import DaemonService
from hueberry.backend.devices import describe_device
from hueberry.ui import lighting_panel as lighting_module
from hueberry.ui import worker
from hueberry.ui.daemon_panel import DaemonPanel
from hueberry.ui.device_info_panel import DeviceInfoPanel
from hueberry.ui.lighting_panel import PRESET_ERHEART, LightingPanel
from hueberry.ui.mouse_panel import MousePanel

UI_DIR = Path(__file__).resolve().parent.parent / "hueberry" / "ui"
FORBIDDEN_IMPORTS = ("import openrazer", "from openrazer")
LIGHTING_CAPS = ("lighting", "lighting_static", "lighting_breath_dual")
MOUSE_CAPS = ("dpi", "poll_rate")
CHOSEN_COLOUR = (10, 20, 30)
NEW_DPI = 1600
UNLOCKED_DPI = 2000


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


@pytest.fixture
def sync_worker(monkeypatch):
    """Make worker.run_async run synchronously."""
    monkeypatch.setattr(worker, "run_async", _run_sync)


def _select_effect(panel, key):
    index = panel.effect_combo.findData(key)
    assert index >= 0, key
    panel.effect_combo.setCurrentIndex(index)


@pytest.fixture
def lighting_panel(qtbot):
    panel = LightingPanel()
    qtbot.addWidget(panel)
    return panel


def test_secondary_colour_hidden_for_static_shown_for_dual(lighting_panel, make_device):
    dev = make_device(device_type="keyboard", capabilities=LIGHTING_CAPS)
    lighting_panel.set_device(dev)
    _select_effect(lighting_panel, "static")
    assert lighting_panel.colour1_button.isVisibleTo(lighting_panel)
    assert not lighting_panel.colour2_button.isVisibleTo(lighting_panel)
    assert not lighting_panel.speed_combo.isVisibleTo(lighting_panel)
    _select_effect(lighting_panel, "breath_dual")
    assert lighting_panel.colour2_button.isVisibleTo(lighting_panel)


def test_apply_calls_backend(lighting_panel, make_device, sync_worker):
    dev = make_device(device_type="keyboard", capabilities=LIGHTING_CAPS)
    lighting_panel.set_device(dev)
    _select_effect(lighting_panel, "static")
    lighting_panel.colour1_button.set_colour(CHOSEN_COLOUR)
    messages = []
    lighting_panel.status.connect(messages.append)
    lighting_panel.apply_button.click()
    assert dev.fx.calls == [("static", CHOSEN_COLOUR)]
    assert messages == ["Applied Static"]


def test_apply_error_goes_to_status(lighting_panel, make_device, sync_worker):
    dev = make_device(device_type="keyboard", capabilities=LIGHTING_CAPS)
    lighting_panel.set_device(dev)
    dev.capabilities.clear()  # effect now unsupported -> LightingError
    messages = []
    lighting_panel.status.connect(messages.append)
    lighting_panel.apply_button.click()
    assert messages and messages[0].startswith("Lighting error")


def test_brightness_slider_enabled_only_when_supported(lighting_panel, make_device):
    lighting_panel.set_device(make_device(capabilities=LIGHTING_CAPS))
    assert not lighting_panel.brightness_slider.isEnabled()
    lighting_panel.set_device(make_device(capabilities=LIGHTING_CAPS + ("brightness",)))
    assert lighting_panel.brightness_slider.isEnabled()


class _Capture:
    """run_async stand-in that records calls without running them."""

    def __init__(self):
        self.calls = []

    def __call__(self, fn, on_done=None, on_error=None):
        self.calls.append((fn, on_done, on_error))


@pytest.fixture
def capture_worker(monkeypatch):
    """Make worker.run_async record calls without running them."""
    capture = _Capture()
    monkeypatch.setattr(worker, "run_async", capture)
    return capture


BRIGHTNESS_CAPS = LIGHTING_CAPS + ("brightness",)
LOADED_BRIGHTNESS = 40.0


def test_loading_brightness_does_not_write(lighting_panel, make_device, capture_worker):
    dev = make_device(capabilities=BRIGHTNESS_CAPS)
    dev.brightness = LOADED_BRIGHTNESS
    lighting_panel.set_device(dev)
    assert lighting_panel.brightness_slider.value() == LOADED_BRIGHTNESS
    assert capture_worker.calls == []


def test_brightness_keyboard_and_page_step_apply(qtbot, lighting_panel, make_device,
                                                 sync_worker):
    dev = make_device(capabilities=BRIGHTNESS_CAPS)
    dev.brightness = LOADED_BRIGHTNESS
    lighting_panel.set_device(dev)
    slider = lighting_panel.brightness_slider
    qtbot.keyClick(slider, Qt.Key.Key_Right)
    assert dev.brightness == LOADED_BRIGHTNESS + slider.singleStep()
    slider.triggerAction(QAbstractSlider.SliderAction.SliderPageStepAdd)
    assert dev.brightness == LOADED_BRIGHTNESS + slider.singleStep() + slider.pageStep()


def test_brightness_drag_applies_on_release_only(lighting_panel, make_device, capture_worker):
    lighting_panel.set_device(make_device(capabilities=BRIGHTNESS_CAPS))
    slider = lighting_panel.brightness_slider
    slider.setSliderDown(True)
    slider.setValue(10)
    slider.setValue(20)
    assert capture_worker.calls == []
    slider.setSliderDown(False)  # emits sliderReleased
    assert len(capture_worker.calls) == 1


def test_apply_disabled_while_write_pending(lighting_panel, make_device, capture_worker):
    dev = make_device(capabilities=BRIGHTNESS_CAPS)
    lighting_panel.set_device(dev)
    _select_effect(lighting_panel, "static")
    lighting_panel.apply_button.click()
    assert len(capture_worker.calls) == 1
    assert not lighting_panel.apply_button.isEnabled()
    lighting_panel.brightness_slider.setValue(30)  # queued, not submitted
    assert len(capture_worker.calls) == 1
    fn, on_done, _on_error = capture_worker.calls[0]
    on_done(fn())
    assert lighting_panel.apply_button.isEnabled() is False  # queued brightness now pending
    assert len(capture_worker.calls) == 2
    fn, on_done, _on_error = capture_worker.calls[1]
    on_done(fn())
    assert dev.brightness == 30
    assert lighting_panel.apply_button.isEnabled()


def test_apply_reenabled_after_error(lighting_panel, make_device, capture_worker):
    lighting_panel.set_device(make_device(capabilities=LIGHTING_CAPS))
    _select_effect(lighting_panel, "static")
    lighting_panel.apply_button.click()
    _fn, _on_done, on_error = capture_worker.calls[0]
    on_error("boom")
    assert lighting_panel.apply_button.isEnabled()


def test_lighting_callbacks_survive_deleted_panel(qtbot, make_device, capture_worker):
    panel = LightingPanel()
    panel.set_device(make_device(capabilities=LIGHTING_CAPS))
    _select_effect(panel, "static")
    panel.apply_button.click()
    _fn, on_done, on_error = capture_worker.calls[0]
    sip.delete(panel)
    on_done(True)
    on_error("late")


MATRIX_CAPS = LIGHTING_CAPS + ("lighting_led_matrix",)


@pytest.fixture
def passive_animator(monkeypatch):
    """Replace the shared animator with a thread-less one."""
    anim = animator.Animator(start_thread=False)
    monkeypatch.setattr(animator, "shared_animator", lambda: anim)
    return anim


def test_erheart_offered_when_supported(lighting_panel, make_device, passive_animator):
    lighting_panel.set_device(make_device(capabilities=LIGHTING_CAPS))
    index = lighting_panel.effect_combo.findData(PRESET_ERHEART)
    assert index >= 0
    assert lighting_panel.effect_combo.itemText(index) == "Erheart"
    lighting_panel.set_device(make_device(capabilities=("lighting", "lighting_spectrum")))
    assert lighting_panel.effect_combo.findData(PRESET_ERHEART) < 0


def test_apply_erheart_starts_animation(lighting_panel, make_device, passive_animator,
                                        capture_worker):
    dev = make_device(serial="KBD1", capabilities=MATRIX_CAPS)
    lighting_panel.set_device(dev)
    _select_effect(lighting_panel, PRESET_ERHEART)
    assert lighting_panel.apply_button.isEnabled()
    messages = []
    lighting_panel.status.connect(messages.append)
    lighting_panel.apply_button.click()
    assert messages == ["Applied Erheart"]
    assert capture_worker.calls == []  # frames are drawn by the animator, not the worker
    assert passive_animator.is_running("KBD1")
    passive_animator.step()
    assert len(dev.fx.advanced.draws) == 1


def test_other_effect_stops_erheart(lighting_panel, make_device, passive_animator,
                                    capture_worker, monkeypatch):
    dev = make_device(serial="KBD1", capabilities=MATRIX_CAPS)
    lighting_panel.set_device(dev)
    _select_effect(lighting_panel, PRESET_ERHEART)
    lighting_panel.apply_button.click()
    lighting_panel.set_device(dev)  # re-showing the device must not stop it
    assert passive_animator.is_running("KBD1")
    seen = []
    real_apply = lighting_module.apply_effect

    def apply_after_stop(*args):
        seen.append((passive_animator.is_running("KBD1"), dev.fx.advanced.restore_calls))
        return real_apply(*args)

    monkeypatch.setattr(lighting_module, "apply_effect", apply_after_stop)
    _select_effect(lighting_panel, "static")
    lighting_panel.apply_button.click()
    assert passive_animator.is_running("KBD1")  # nothing is stopped on the UI thread
    ((fn, on_done, _on_error),) = capture_worker.calls
    on_done(fn())
    assert seen == [(False, 1)]  # stopped and restored inside the job, before apply_effect
    assert not passive_animator.is_running("KBD1")
    assert dev.fx.calls[-1][0] == "static"


@pytest.fixture
def mouse_panel(qtbot):
    container = QWidget()
    qtbot.addWidget(container)
    return MousePanel(container), container


def test_mouse_lock_syncs_y(mouse_panel, make_device):
    panel, _container = mouse_panel
    panel.set_device(make_device(capabilities=MOUSE_CAPS))
    assert panel.lock_check.isChecked()
    panel.dpi_x_spin.setValue(NEW_DPI)
    assert panel.dpi_y_spin.value() == NEW_DPI
    assert panel.dpi_slider.value() == NEW_DPI
    assert not panel.dpi_y_spin.isEnabled()
    panel.lock_check.setChecked(False)
    assert panel.dpi_y_spin.isEnabled()
    panel.dpi_x_spin.setValue(UNLOCKED_DPI)
    assert panel.dpi_y_spin.value() == NEW_DPI


def test_mouse_apply_sets_dpi_and_poll_rate(mouse_panel, make_device, sync_worker):
    panel, _container = mouse_panel
    dev = make_device(capabilities=MOUSE_CAPS)
    panel.set_device(dev)
    panel.dpi_x_spin.setValue(NEW_DPI)
    panel.poll_combo.setCurrentIndex(panel.poll_combo.findData(500))
    panel.apply_button.click()
    assert dev.dpi == (NEW_DPI, NEW_DPI)
    assert dev.poll_rate == 500


def test_mouse_apply_disabled_while_pending(mouse_panel, make_device, capture_worker):
    panel, _container = mouse_panel
    panel.set_device(make_device(capabilities=MOUSE_CAPS))
    panel.apply_button.click()
    assert len(capture_worker.calls) == 1
    assert not panel.apply_button.isEnabled()
    _fn, on_done, _on_error = capture_worker.calls[0]
    on_done((NEW_DPI, NEW_DPI))
    assert panel.apply_button.isEnabled()
    panel.apply_button.click()
    _fn, _on_done, on_error = capture_worker.calls[1]
    on_error("boom")
    assert panel.apply_button.isEnabled()


def test_mouse_callbacks_survive_deleted_panel(qapp, make_device, capture_worker):
    panel = MousePanel()
    panel.set_device(make_device(capabilities=MOUSE_CAPS))
    panel.apply_button.click()
    _fn, on_done, on_error = capture_worker.calls[0]
    sip.delete(panel)
    on_done((NEW_DPI, NEW_DPI))
    on_error("late")


def test_mouse_panel_hidden_for_non_mouse(mouse_panel, make_device):
    panel, container = mouse_panel
    panel.set_device(make_device(capabilities=MOUSE_CAPS))
    assert panel.isVisibleTo(container)
    panel.set_device(make_device(device_type="keyboard", capabilities=LIGHTING_CAPS))
    assert not panel.isVisibleTo(container)
    panel.set_device(None)
    assert not panel.isVisibleTo(container)


def test_device_info_panel_shows_fields(qtbot, make_device):
    panel = DeviceInfoPanel()
    qtbot.addWidget(panel)
    panel.set_device(describe_device(make_device(serial="XX123")))
    assert panel.values["serial"].text() == "XX123"
    panel.set_device(None)
    assert panel.values["serial"].text() != "XX123"


@pytest.fixture
def daemon_panel(qtbot, tmp_path, fake_manager_factory):
    service = DaemonService(pid_path=tmp_path / "missing.pid")
    panel = DaemonPanel(service)
    qtbot.addWidget(panel)
    return panel, service


def test_repoll_calls_service_and_emits(qtbot, daemon_panel, fake_manager_factory, sync_worker):
    panel, service = daemon_panel
    with qtbot.waitSignal(panel.daemon_changed, timeout=1000):
        panel.repoll_button.click()
    assert fake_manager_factory.constructions == 1
    assert service.connected
    assert panel.daemon_version_value.text() == "3.12.1-fake"
    assert panel.sync_check.isEnabled()


def test_stop_declined_does_not_stop(daemon_panel, fake_manager_factory, sync_worker):
    panel, service = daemon_panel
    assert service.connect()
    panel.refresh()
    panel.confirm_stop = lambda: False
    panel.stop_button.click()
    assert fake_manager_factory.instances[0].stop_calls == 0
    assert service.connected


def test_stop_confirmed_stops(daemon_panel, fake_manager_factory, sync_worker):
    panel, service = daemon_panel
    assert service.connect()
    panel.refresh()
    panel.confirm_stop = lambda: True
    panel.stop_button.click()
    assert fake_manager_factory.instances[0].stop_calls == 1


def test_run_async_reports_result_and_error(qtbot):
    results, errors = [], []
    worker.run_async(lambda: 42, results.append, errors.append)
    worker.run_async(lambda: 1 / 0, results.append, errors.append)
    qtbot.waitUntil(lambda: results == [42] and len(errors) == 1, timeout=2000)


def test_ui_does_not_import_openrazer():
    files = sorted(UI_DIR.rglob("*.py"))
    assert files
    for path in files:
        text = path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_IMPORTS:
            assert forbidden not in text, path
