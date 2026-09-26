# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the main window's preset wiring: restore on reload, presets_saved."""

import json

import pytest
from PyQt6.QtWidgets import QAbstractButton, QLabel, QTabWidget

from hueberry.backend import animator, lighting_state, preset_store
from hueberry.backend.daemon import DaemonService
from hueberry.backend.effects import EFFECT_WAVE, Preset
from hueberry.ui import worker
from hueberry.ui.lighting_panel import preset_data
from hueberry.ui.main_window import PRESETS_TEXT, MainWindow

MOUSE_SERIAL = "MOUSE0001"
KEYBOARD_SERIAL = "KBD0001"
MOUSE_CAPS = ("dpi", "poll_rate", "lighting", "lighting_static")
KEYBOARD_CAPS = ("lighting", "lighting_static")
MNEMONIC = "&"
BROKEN_FILE = b"{ not json"
STATE_FILE = json.dumps({"version": 1, "assignments": [
    {"preset_key": "sunset", "mode": "single", "serials": [MOUSE_SERIAL]}]}).encode()
SUNSET = Preset(key="sunset", label="Sunset", effect=EFFECT_WAVE,
                palette=((255, 80, 0), (120, 0, 200)))


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


class _RecordingState:
    """Stands in for the shared lighting state; records restore calls."""

    def __init__(self, error=None):
        self.error = error
        self.restored = []

    def restore(self, devices):
        self.restored.append([dev.serial for dev in devices])
        return self.error


@pytest.fixture
def recorder(monkeypatch):
    state = _RecordingState()
    monkeypatch.setattr(lighting_state, "shared_lighting_state", lambda: state)
    return state


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch, fake_manager_factory, make_device, recorder):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(worker, "run_async", _run_sync)
    passive = animator.Animator(start_thread=False)
    monkeypatch.setattr(animator, "shared_animator", lambda: passive)
    fake_manager_factory.devices = [
        make_device(name="Test Mouse", device_type="mouse", serial=MOUSE_SERIAL,
                    capabilities=MOUSE_CAPS),
        make_device(name="Test Keyboard", device_type="keyboard", serial=KEYBOARD_SERIAL,
                    capabilities=KEYBOARD_CAPS),
    ]
    service = DaemonService(pid_path=tmp_path / "missing.pid")
    win = MainWindow(service)
    qtbot.addWidget(win)
    return win, service


def _mnemonic(text):
    """The lower-case mnemonic letter of ``text``, or None."""
    clean = text.replace(MNEMONIC * 2, "")  # "&&" is a literal ampersand
    index = clean.find(MNEMONIC)
    return clean[index + 1].lower() if 0 <= index < len(clean) - 1 else None


def _taken_mnemonics(win):
    """Mnemonic letters of every button, label and tab in ``win`` but the Presets button."""
    widgets = win.findChildren(QAbstractButton) + win.findChildren(QLabel)
    texts = [widget.text() for widget in widgets if widget is not win.presets_button]
    texts += [tabs.tabText(index) for tabs in win.findChildren(QTabWidget)
              for index in range(tabs.count())]
    return {letter for letter in map(_mnemonic, texts) if letter is not None}


def _connect(win):
    win.run_service_action("Connect", win._service.connect)


def test_reload_restores_lighting_state(window, recorder, fake_manager_factory):
    win, _service = window
    _connect(win)
    assert recorder.restored[-1] == [MOUSE_SERIAL, KEYBOARD_SERIAL]
    fake_manager_factory.devices = fake_manager_factory.devices[:1]
    win.repoll_action.trigger()
    assert recorder.restored[-1] == [MOUSE_SERIAL]


def test_restore_error_reaches_status_bar(window, recorder):
    win, _service = window
    recorder.error = "state file was invalid"
    win.reload()
    assert win.statusBar().currentMessage() == "Lighting state: state file was invalid"


def test_presets_mnemonic_does_not_clash(window):
    win, _service = window
    taken = _taken_mnemonics(win)
    assert taken  # the scan does see the window's other mnemonics
    assert win.presets_button.text() == PRESETS_TEXT
    clash = f"{MNEMONIC}{sorted(taken)[0]}"
    assert _mnemonic(clash) in taken  # a taken letter would be caught
    presets = _mnemonic(PRESETS_TEXT)
    assert presets is None or presets not in taken


def test_preset_load_error_reaches_status_bar_at_startup(
        qtbot, tmp_path, monkeypatch, fake_manager_factory, recorder):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(worker, "run_async", _run_sync)
    passive = animator.Animator(start_thread=False)
    monkeypatch.setattr(animator, "shared_animator", lambda: passive)
    path = preset_store.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(BROKEN_FILE)
    fake_manager_factory.devices = []
    win = MainWindow(DaemonService(pid_path=tmp_path / "missing.pid"))
    qtbot.addWidget(win)
    message = win.statusBar().currentMessage()
    assert message and ".bak" in message


def test_corrupt_presets_do_not_drop_lighting_state(
        qtbot, tmp_path, monkeypatch, fake_manager_factory, make_device):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(worker, "run_async", _run_sync)
    passive = animator.Animator(start_thread=False)
    monkeypatch.setattr(animator, "shared_animator", lambda: passive)
    preset_path = preset_store.config_path()
    preset_path.parent.mkdir(parents=True, exist_ok=True)
    preset_path.write_bytes(BROKEN_FILE)
    state_path = lighting_state.config_path()
    state_path.write_bytes(STATE_FILE)
    fake_manager_factory.devices = [
        make_device(name="Test Mouse", device_type="mouse", serial=MOUSE_SERIAL,
                    capabilities=MOUSE_CAPS)]
    win = MainWindow(DaemonService(pid_path=tmp_path / "missing.pid"))
    qtbot.addWidget(win)
    assert not preset_path.exists()  # quarantined by the first read
    _connect(win)
    win.reload()
    assert state_path.read_bytes() == STATE_FILE


def test_presets_saved_reloads_lighting_panel(window):
    win, _service = window
    _connect(win)
    win.home_page.device_activated.emit(KEYBOARD_SERIAL)
    combo = win.lighting_panel.effect_combo
    assert combo.findData(preset_data(SUNSET.key)) < 0
    preset_store.save([SUNSET])
    win.presets_page.presets_saved.emit()
    assert combo.findData(preset_data(SUNSET.key)) >= 0
