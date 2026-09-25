# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the Macros page (fake engine, synchronous worker, tmp config dir)."""

import threading

import pytest
from PyQt6.QtCore import Qt

from hueberry.backend import macro_engine as states
from hueberry.backend.macro_engine import MacroEngineService
from hueberry.macros import store
from hueberry.macros.model import DeviceMacros, KeyStep, Macro, MacroConfig
from hueberry.macros.protocol import EngineUnavailable
from hueberry.ui import worker
from hueberry.ui.macros_page import ENGINE_POLL_MS, MacrosPage, banner_text, state_label

MOUSE = "1532:0084:Test Mouse:usb-1"
KEYBOARD = "1532:0203:Test Keyboard:usb-2"
OLD_PAD = "1532:0999:Old Pad:usb-3"
ALL_OK = {"uinput_ok": True, "unreadable_inputs": []}


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


class FakeEngine:
    """MacroEngineService stand-in."""

    def __init__(self, state=states.STATE_RUNNING, permissions=None, error=None):
        self.state = state
        self.last_error = error
        self.permissions = permissions if permissions is not None else dict(ALL_OK)
        self.states = {MOUSE: "active", KEYBOARD: None}
        self.config_error = None
        self.fail = False
        self.calls = []

    def poll(self):
        return self.state

    def list_devices(self):
        self.calls.append("list_devices")
        if self.fail:
            raise EngineUnavailable("gone")
        devices = [{"identity": MOUSE, "name": "Test Mouse", "has_keys": True, "state": self.states[MOUSE]},
                   {"identity": KEYBOARD, "name": "Test Keyboard", "has_keys": True,
                    "state": self.states[KEYBOARD]},
                   {"identity": "x", "name": "Lid switch", "has_keys": False, "state": None}]
        return {"devices": devices, "permissions": self.permissions}

    def status(self):
        self.calls.append("status")
        devices = [{"identity": MOUSE, "name": "Test Mouse", "state": self.states[MOUSE], "error": None}]
        return {"devices": devices, "recording": None, "config_error": self.config_error}

    def reload(self):
        self.calls.append("reload")
        return self.status()

    def spawn(self):
        self.calls.append("spawn")
        self.state = states.STATE_STARTING
        return True

    def wait_ready(self):
        self.calls.append("wait_ready")
        self.state = states.STATE_RUNNING
        return True


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(worker, "run_async", _run_sync)
    return tmp_path


def _page(qtbot, engine):
    page = MacrosPage(engine)
    qtbot.addWidget(page)
    page.refresh()
    return page


def _device_texts(page):
    return [page.device_list.item(row).text() for row in range(page.device_list.count())]


def _select(page, identity):
    for row in range(page.device_list.count()):
        if page.device_list.item(row).data(Qt.ItemDataRole.UserRole) == identity:
            page.device_list.setCurrentRow(row)
            return
    raise AssertionError(identity)


def _add_macro(page, trigger="BTN_SIDE"):
    page.add_button.click()
    editor = page.editor
    editor.name_edit.setText("Copy")
    editor.trigger_combo.setCurrentText(trigger)
    editor.add_key_button.click()
    editor.step_dialog.accept()
    editor.accept()


def test_state_labels():
    assert state_label("active") == "grabbed"
    assert state_label("waiting") == "waiting for held keys to be released"
    assert state_label("busy").startswith("busy")
    assert state_label(None) == "idle"


def test_device_list_states(qtbot):
    engine = FakeEngine()
    store.save(MacroConfig([DeviceMacros(OLD_PAD, "Old Pad", [])]))
    page = _page(qtbot, engine)
    assert _device_texts(page) == ["Old Pad \u2013 not connected", "Test Keyboard \u2013 idle",
                                   "Test Mouse \u2013 grabbed"]
    engine.states[MOUSE] = "busy"
    page.refresh_button.click()
    assert "Test Mouse \u2013 busy \u2013 used by another program" in _device_texts(page)


def test_banner_hidden_when_all_ok(qtbot):
    page = _page(qtbot, FakeEngine())
    assert page.banner_label.isHidden()
    assert page.start_button.isHidden()


@pytest.mark.parametrize(("engine", "config_error", "expected", "offer_start"), [
    (None, None, "cannot run in this session", False),
    (FakeEngine(states.STATE_EVDEV_MISSING), None, "python-evdev is not installed", False),
    (FakeEngine(states.STATE_STARTING), None, "Starting the macro engine", False),
    (FakeEngine(states.STATE_CRASHED, error="exited with code 1"), None,
     "not running (exited with code 1)", True),
    (FakeEngine(permissions={"uinput_ok": False, "unreadable_inputs": []}), None,
     "No access to /dev/uinput.", False),
    (FakeEngine(permissions={"uinput_ok": True, "unreadable_inputs": ["/dev/input/event3"]}), None,
     "No access to input devices", False),
    (FakeEngine(), "bad file", "macros.json: bad file", False),
])
def test_banner_variants(engine, config_error, expected, offer_start):
    permissions = engine.permissions if engine is not None else {}
    text, start = banner_text(engine, permissions, config_error)
    assert expected in text
    assert start is offer_start


def test_banner_shows_engine_config_error(qtbot):
    engine = FakeEngine()
    engine.config_error = "macros.json was invalid"
    page = _page(qtbot, engine)
    assert not page.banner_label.isHidden()
    assert "was invalid" in page.banner_label.text()


def test_start_engine_button(qtbot):
    engine = FakeEngine(states.STATE_CRASHED)
    page = _page(qtbot, engine)
    assert not page.start_button.isHidden()
    with qtbot.waitSignal(page.engine_summary, timeout=1000):
        page.start_button.click()
    assert engine.calls[:2] == ["spawn", "wait_ready"]
    assert page.banner_label.isHidden()


class _Process:
    pid = 1

    def poll(self):
        return None


class _Client:
    """Engine client stand-in recording the thread of the first request (the ping)."""

    def __init__(self, threads):
        self.threads = threads

    def request(self, op, **_args):
        self.threads.setdefault("request", threading.current_thread())
        return {"devices": [], "permissions": {}} if op == "list_devices" else {"devices": []}


def _run_on_worker_thread(fn, on_done=None, on_error=None):
    """run_async stand-in: fn runs on a real (short-lived) thread, callbacks on this one."""
    box = {}
    thread = threading.Thread(target=lambda: box.setdefault("result", fn()))
    thread.start()
    thread.join()
    if on_done is not None:
        on_done(box["result"])


def test_engine_is_spawned_on_the_gui_thread(qtbot, monkeypatch):
    """PR_SET_PDEATHSIG kills the engine when the forking thread exits: never fork on a worker."""
    threads = {}

    def popen(_argv, **_kwargs):
        threads["popen"] = threading.current_thread()
        return _Process()

    monkeypatch.setattr(worker, "run_async", _run_on_worker_thread)
    engine = MacroEngineService(popen=popen, sleep=lambda _s: None, client=_Client(threads),
                                python="python3", parent_pid=1)
    page = MacrosPage(engine)
    qtbot.addWidget(page)
    page.start_engine()
    assert threads["popen"] is threading.main_thread()
    assert threads["request"] is not threading.main_thread()
    assert engine.state == states.STATE_RUNNING


def test_poll_timer_notices_crash(qtbot):
    engine = FakeEngine()
    page = _page(qtbot, engine)
    assert page.poll_timer.isActive()
    assert page.poll_timer.interval() == ENGINE_POLL_MS
    page._poll_engine()
    summaries = []
    page.engine_summary.connect(summaries.append)
    engine.state, engine.last_error = states.STATE_CRASHED, "exited with code 1"
    page._poll_engine()
    assert summaries == ["not running"]
    assert "exited with code 1" in page.banner_label.text()
    assert not page.start_button.isHidden()
    page._poll_engine()
    assert summaries == ["not running"]  # unchanged state: no redundant update


def test_no_poll_timer_without_engine(qtbot):
    page = MacrosPage(None)
    qtbot.addWidget(page)
    assert not page.poll_timer.isActive()


def test_save_writes_config_and_reloads(qtbot, env):
    engine = FakeEngine()
    page = _page(qtbot, engine)
    _select(page, MOUSE)
    assert not page.save_button.isEnabled()
    _add_macro(page)
    assert page.save_button.isEnabled()
    engine.calls.clear()
    with qtbot.waitSignal(page.status, timeout=1000):
        page.save_button.click()
    config, error = store.load(env / "hueberry" / "macros.json")
    assert error is None
    (device,) = config.devices
    assert device.identity == MOUSE and device.name == "Test Mouse"
    assert [(m.name, m.trigger, m.steps) for m in device.macros] == [("Copy", "BTN_SIDE", [KeyStep("KEY_A")])]
    assert engine.calls[0] == "reload"
    assert not page.save_button.isEnabled()


def test_editing_while_engine_down(qtbot, env):
    engine = FakeEngine(states.STATE_CRASHED)
    store.save(MacroConfig([DeviceMacros(MOUSE, "Test Mouse", [
        Macro("m1", "Old", True, "BTN_EXTRA", [KeyStep("KEY_B")])])]))
    page = _page(qtbot, engine)
    assert _device_texts(page) == ["Test Mouse \u2013 not connected"]
    page.macro_list.setCurrentRow(0)
    page.edit_button.click()
    assert not page.editor.record_button.isEnabled()
    page.editor.name_edit.setText("Renamed")
    page.editor.accept()
    page.macro_list.item(0).setCheckState(Qt.CheckState.Unchecked)
    messages = []
    page.status.connect(messages.append)
    page.save_button.click()
    assert messages == ["Macros saved; they apply once the macro engine runs"]
    assert "reload" not in engine.calls
    config, _error = store.load()
    macro = config.devices[0].macros[0]
    assert (macro.name, macro.enabled) == ("Renamed", False)


def test_fetch_failure_falls_back_to_config(qtbot):
    engine = FakeEngine()
    engine.fail = True
    store.save(MacroConfig([DeviceMacros(MOUSE, "Test Mouse", [])]))
    page = _page(qtbot, engine)
    assert _device_texts(page) == ["Test Mouse \u2013 not connected"]


def test_duplicate_trigger_blocked(qtbot):
    page = _page(qtbot, FakeEngine())
    _select(page, MOUSE)
    _add_macro(page)
    page.add_button.click()
    page.editor.trigger_combo.setCurrentText("BTN_SIDE")
    assert "already triggers another macro" in page.editor.validation_label.text()


def test_delete_macro(qtbot):
    page = _page(qtbot, FakeEngine())
    _select(page, MOUSE)
    _add_macro(page)
    page.macro_list.setCurrentRow(0)
    page.delete_button.click()
    assert page.macro_list.count() == 0
    assert page.save_button.isEnabled()


def test_back_button(qtbot):
    page = _page(qtbot, FakeEngine())
    with qtbot.waitSignal(page.back_requested, timeout=1000):
        page.back_button.click()
