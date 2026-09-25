# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the engine server loop and the engine entry point.

Sockets live under a short /tmp directory (AF_UNIX paths are limited to 108
bytes). The loop is driven with ``run_once(0)`` so no test sleeps.
"""

import json
import os
import shutil
import signal
import socket
import stat
import tempfile
from pathlib import Path

import pytest
from fake_evdev import make_event

from hueberry.macro_engine import devices
from hueberry.macro_engine import main as main_mod
from hueberry.macro_engine.server import AlreadyRunning, EngineServer
from hueberry.macros.model import DeviceMacros, KeyStep, Macro, MacroConfig

EV_SYN, EV_KEY = 0, 1
BTN_LEFT, BTN_SIDE, KEY_A = 0x110, 0x113, 30
MAX_ALIVE_CHECKS = 100  # guard: a serve() loop in a test can never spin forever


class _Watcher:
    """Injected parent watcher: optional pipe fd plus a scripted alive flag (bounded)."""

    def __init__(self, fd=None):
        self.fd = fd
        self.is_alive = True
        self.checks = 0

    def fileno(self):
        return self.fd

    def alive(self):
        self.checks += 1
        return self.is_alive and self.checks < MAX_ALIVE_CHECKS


@pytest.fixture
def sock_dir():
    path = Path(tempfile.mkdtemp(prefix="hbm", dir="/tmp"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def mouse(fake_evdev):
    return fake_evdev.InputDevice("/dev/input/event5", name="Razer Naga", keys=[BTN_LEFT, BTN_SIDE],
                                  phys="usb-1/input0")


@pytest.fixture
def keyboard(fake_evdev):
    return fake_evdev.InputDevice("/dev/input/event6", name="Keyboard", keys=[KEY_A], phys="usb-2/input0")


def _config(dev, enabled=True):
    macro = Macro("m1", "Type A", enabled, "BTN_SIDE", [KeyStep("KEY_A")])
    return MacroConfig([DeviceMacros(devices.identity(dev), dev.name, [macro])])


class _Loader:
    def __init__(self, config, error=None):
        self.config = config
        self.error = error

    def __call__(self):
        return self.config, self.error


def _server(sock_dir, config, watcher=None, **kwargs):
    kwargs.setdefault("poll_interval", 0)
    return EngineServer(sock_dir / "engine.sock", parent_watcher=watcher or _Watcher(), load_config=_Loader(config),
                        **kwargs)


def _ask(server, op, **args):
    return server.handle_line(json.dumps({"op": op, "args": args}).encode())


def test_setup_socket_modes_and_status(sock_dir, mouse):
    """Socket dir 0700 and socket 0600; configured device is grabbed and reported."""
    server = _server(sock_dir, _config(mouse))
    server.setup()
    try:
        assert stat.S_IMODE(os.stat(sock_dir).st_mode) == 0o700
        assert stat.S_IMODE(os.stat(server.path).st_mode) == 0o600
        assert mouse.grabbed
        reply = _ask(server, "status")
        assert reply["ok"]
        assert reply["result"]["devices"] == [{"identity": devices.identity(mouse), "name": "Razer Naga",
                                               "state": "active", "error": None}]
    finally:
        server.close()
    assert not mouse.grabbed and not server.path.exists()


def test_request_over_socket_and_bad_requests(sock_dir, mouse):
    """A real client line gets a reply; unknown ops and garbage get errors."""
    server = _server(sock_dir, MacroConfig())
    server.setup()
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(str(server.path))
        client.sendall(b'{"op":"ping"}\n{"op":"shell","args":{}}\nnot json\n')
        for _ in range(3):
            server.run_once(0)
        client.settimeout(1.0)
        data = b""
        while data.count(b"\n") < 3:
            data += client.recv(4096)
        replies = [json.loads(line) for line in data.splitlines()]
        assert replies[0]["ok"] and replies[0]["result"]["pong"]
        assert not replies[1]["ok"] and "unknown op" in replies[1]["error"]
        assert not replies[2]["ok"]
        assert not _ask(server, "record_stop")["ok"]
        assert not _ask(server, "record_start")["ok"]
    finally:
        client.close()
        server.close()


def test_passthrough_and_trigger_through_loop(sock_dir, fake_evdev, mouse):
    """Device events read by the loop are remapped through the uinput clone."""
    server = _server(sock_dir, _config(mouse))
    server.setup()
    try:
        (clone,) = fake_evdev.UInput.instances
        mouse.queue_events(make_event(EV_KEY, BTN_LEFT, 1), make_event(EV_SYN, 0, 0))
        server.run_once(0)
        assert clone.writes == [(EV_KEY, BTN_LEFT, 1), (EV_SYN, 0, 0)]
    finally:
        server.close()


def test_reload_rebuilds_remappers(sock_dir, fake_evdev, mouse):
    """reload stops old remappers (ungrab) and builds new ones from the file."""
    server = _server(sock_dir, _config(mouse))
    server.setup()
    try:
        server._load_config.config = _config(mouse, enabled=False)
        reply = _ask(server, "reload")
        assert reply["ok"] and reply["result"]["devices"] == []
        assert not mouse.grabbed and mouse.ungrab_calls == 1 and mouse.closed
        server._load_config.config = _config(mouse)
        server._load_config.error = "macros.json was invalid"
        reply = _ask(server, "reload")
        assert reply["result"]["devices"][0]["state"] == "active"
        assert reply["result"]["config_error"] == "macros.json was invalid"
        assert mouse.grabbed and len(fake_evdev.UInput.instances) == 2
    finally:
        server.close()


def test_busy_device_reported_and_not_kept_open(sock_dir, mouse):
    """A device grabbed elsewhere is reported busy and closed again."""
    mouse.grab_error = 16  # EBUSY
    server = _server(sock_dir, _config(mouse))
    server.setup()
    try:
        assert _ask(server, "status")["result"]["devices"][0]["state"] == "busy"
        assert mouse.closed
    finally:
        server.close()


def test_list_devices_reports_permissions(sock_dir, mouse, keyboard):
    """list_devices returns every device and the permission report."""
    report = devices.PermissionReport(False, ("/dev/input/event9",))
    server = _server(sock_dir, _config(mouse), check_permissions=lambda: report)
    server.setup()
    try:
        result = _ask(server, "list_devices")["result"]
        assert [(d["name"], d["state"]) for d in result["devices"]] == [("Razer Naga", "active"),
                                                                         ("Keyboard", None)]
        assert result["permissions"] == {"uinput_ok": False, "unreadable_inputs": ["/dev/input/event9"]}
    finally:
        server.close()


def test_record_round_trip_ungrabbed(sock_dir, keyboard):
    """Recording an unmapped device opens it without grabbing and closes it after."""
    server = _server(sock_dir, MacroConfig())
    server.setup()
    try:
        identity = devices.identity(keyboard)
        assert _ask(server, "record_start", identity=identity)["ok"]
        assert not _ask(server, "record_start", identity=identity)["ok"]
        assert keyboard.grab_calls == 0 and not keyboard.closed
        keyboard.queue_events(make_event(EV_KEY, KEY_A, 1, 5.0), make_event(EV_KEY, KEY_A, 2, 5.1),
                              make_event(EV_KEY, KEY_A, 0, 5.2))
        server.run_once(0)
        assert _ask(server, "status")["result"]["recording"] == identity
        result = _ask(server, "record_stop")["result"]
        assert result["events"] == [["KEY_A", 1, 0.0], ["KEY_A", 0, 0.2]]
        assert keyboard.closed
        assert not _ask(server, "record_start", identity="nope")["ok"]
    finally:
        server.close()


def test_record_on_remapped_device_keeps_grab(sock_dir, mouse):
    """Recording a remapped device reuses its grabbed handle."""
    server = _server(sock_dir, _config(mouse))
    server.setup()
    try:
        assert _ask(server, "record_start", identity=devices.identity(mouse))["ok"]
        mouse.queue_events(make_event(EV_KEY, BTN_LEFT, 1, 1.0))
        server.run_once(0)
        assert _ask(server, "record_stop")["result"]["events"] == [["BTN_LEFT", 1, 0.0]]
        assert mouse.grabbed and not mouse.closed
    finally:
        server.close()


def test_stale_socket_is_replaced(sock_dir):
    """A socket file nobody listens on is unlinked and rebound."""
    path = sock_dir / "engine.sock"
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale.bind(str(path))
    stale.close()
    server = _server(sock_dir, MacroConfig())
    server.setup()
    try:
        assert server.path.exists()
    finally:
        server.close()


def test_already_running_refuses_and_keeps_socket(sock_dir):
    """A socket the (injected) probe reports live makes a second engine refuse and leave it."""
    first = _server(sock_dir, MacroConfig())
    first.setup()
    try:
        second = _server(sock_dir, MacroConfig(), probe=lambda path: True)
        with pytest.raises(AlreadyRunning):
            second.serve()
        assert first.path.exists()
    finally:
        first.close()
    assert not first.path.exists()


def test_held_key_defers_grab_until_release(sock_dir, fake_evdev, mouse):
    """A button held at start delays the grab; events pass untouched until it is released."""
    mouse.held_keys = [BTN_LEFT]
    server = _server(sock_dir, _config(mouse))
    server.setup()
    try:
        (clone,) = fake_evdev.UInput.instances
        assert not mouse.grabbed and not mouse.closed
        assert _ask(server, "status")["result"]["devices"][0]["state"] == "waiting"
        mouse.held_keys = []
        mouse.queue_events(make_event(EV_KEY, BTN_LEFT, 0))
        server.run_once(0)
        assert mouse.grabbed and clone.writes == [] and not clone.closed
        assert _ask(server, "status")["result"]["devices"][0]["state"] == "active"
    finally:
        server.close()
    assert not mouse.grabbed and clone.closed


def test_parent_death_releases_everything(sock_dir, mouse):
    """When the watcher reports the parent gone the loop exits, ungrabs and unlinks."""
    watcher = _Watcher()
    watcher.is_alive = False
    server = _server(sock_dir, _config(mouse), watcher=watcher, poll_interval=0)
    server.serve()
    assert mouse.ungrab_calls == 1 and not mouse.grabbed
    assert not server.path.exists()
    assert server.stop_reason == "parent process is gone"


def test_parent_pidfd_readable_stops_loop(sock_dir, mouse):
    """A readable parent fd (pidfd) ends the loop just like a failed alive()."""
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, b"x")
        server = _server(sock_dir, _config(mouse), watcher=_Watcher(read_fd), poll_interval=0)
        server.serve()
        assert server.stop_reason == "parent process exited"
        assert mouse.ungrab_calls == 1 and not server.path.exists()
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_sigterm_releases_everything(sock_dir, mouse):
    """SIGTERM via the installed handler stops the loop and cleans up."""
    server = _server(sock_dir, _config(mouse))
    previous = main_mod.install_signal_handlers(server)
    try:
        signal.raise_signal(signal.SIGTERM)
        server.serve()
    finally:
        main_mod.restore_signal_handlers(previous)
    assert server.stop_reason == "signal SIGTERM"
    assert mouse.ungrab_calls == 1 and not server.path.exists()


def test_exception_releases_everything(sock_dir, mouse):
    """An unexpected exception in the loop still ungrabs and removes the socket."""
    mouse.read_error = RuntimeError("boom")
    mouse.queue_events(make_event(EV_KEY, BTN_LEFT, 1))
    server = _server(sock_dir, _config(mouse))
    with pytest.raises(RuntimeError, match="boom"):
        server.serve()
    assert mouse.ungrab_calls == 1 and not server.path.exists()
    assert main_mod.run_server(_server(sock_dir, _config(mouse))) == main_mod.EXIT_ERROR


def test_unplugged_device_is_dropped(sock_dir, mouse):
    """A read OSError (device gone) releases the device and reports it."""
    server = _server(sock_dir, _config(mouse))
    server.setup()
    try:
        mouse.read_error = OSError(19, "No such device")
        mouse.queue_events(make_event(EV_KEY, BTN_LEFT, 1))
        server.run_once(0)
        assert _ask(server, "status")["result"]["devices"][0]["state"] == "disconnected"
        assert mouse.closed
    finally:
        server.close()
