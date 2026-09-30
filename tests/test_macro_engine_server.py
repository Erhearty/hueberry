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
REL_X = 0x00
LOGITECH_VENDOR = 0x046D
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


@pytest.fixture
def naga_nodes(fake_evdev):
    """One physical mouse exposed as three event nodes (keyboard, mouse, keyboard interfaces)."""
    keys = ([KEY_A], [BTN_LEFT, BTN_SIDE], [KEY_A])
    return [fake_evdev.InputDevice(f"/dev/input/event{20 + index}", name="Razer Naga", keys=node_keys,
                                   phys=f"usb-3/input{index}") for index, node_keys in enumerate(keys)]


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
        assert not keyboard.grabbed and keyboard.grab_calls == keyboard.ungrab_calls and not keyboard.closed
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


def test_record_across_all_nodes_of_identity(sock_dir, naga_nodes):
    """Events on the 2nd of 3 nodes of one device are recorded; every node is closed afterwards."""
    server = _server(sock_dir, MacroConfig())
    server.setup()
    try:
        identity = devices.identity(naga_nodes[0])
        assert _ask(server, "record_start", identity=identity)["ok"]
        assert sorted(server._handles) == [node.path for node in naga_nodes]
        assert all(not node.grabbed and not node.closed for node in naga_nodes)
        naga_nodes[1].queue_events(make_event(EV_KEY, BTN_SIDE, 1, 2.0), make_event(EV_KEY, BTN_SIDE, 0, 2.1))
        server.run_once(0)
        result = _ask(server, "record_stop")["result"]
        assert result["events"] == [["BTN_SIDE", 1, 0.0], ["BTN_SIDE", 0, 0.1]]
        assert server._handles == {} and all(node.closed for node in naga_nodes)
    finally:
        server.close()


def test_record_skips_nodes_that_fail_to_open(sock_dir, fake_evdev, naga_nodes):
    """A node that cannot be opened is skipped; recording uses the rest; none opened is an error."""
    failing = {naga_nodes[0].path}

    def _open(path):
        if path in failing:
            raise OSError(13, "Permission denied")
        return fake_evdev.InputDevice(path)

    server = _server(sock_dir, MacroConfig(), open_device=_open)
    server.setup()
    try:
        identity = devices.identity(naga_nodes[0])
        assert _ask(server, "record_start", identity=identity)["ok"]
        assert sorted(server._handles) == [naga_nodes[1].path, naga_nodes[2].path]
        _ask(server, "record_stop")
        failing.update(node.path for node in naga_nodes)
        reply = _ask(server, "record_start", identity=identity)
        assert not reply["ok"] and server._handles == {}
    finally:
        server.close()


def test_list_devices_one_row_per_identity(sock_dir, naga_nodes):
    """Three nodes of one device are listed as one row carrying every path."""
    server = _server(sock_dir, _config(naga_nodes[0]))
    server.setup()
    try:
        (row,) = _ask(server, "list_devices")["result"]["devices"]
        assert row == {"identity": devices.identity(naga_nodes[0]), "path": naga_nodes[0].path,
                       "name": "Razer Naga", "vendor": "1532", "kind": "keyboard", "has_keys": True,
                       "state": "active", "paths": [node.path for node in naga_nodes]}
    finally:
        server.close()


def _list_rows(sock_dir):
    server = _server(sock_dir, MacroConfig())
    server.setup()
    try:
        return _ask(server, "list_devices")["result"]["devices"]
    finally:
        server.close()


def test_list_devices_kind_from_primary_pointer(sock_dir, fake_evdev):
    """A pointer on input0 makes the identity a mouse even though input1 has KEY_A."""
    configs = ({"keys": [BTN_LEFT, BTN_SIDE], "rel": [REL_X]}, {"keys": [KEY_A]}, {"keys": [BTN_SIDE]})
    for index, config in enumerate(configs):
        fake_evdev.InputDevice(f"/dev/input/event{30 + index}", name="Gaming Mouse", phys=f"usb-4/input{index}",
                               **config)
    (row,) = _list_rows(sock_dir)
    assert row["kind"] == "mouse"


def test_list_devices_kind_from_primary_keyboard(sock_dir, fake_evdev):
    """A keyboard with a pointer interface on input2 stays a keyboard."""
    configs = ({"keys": [KEY_A]}, {"keys": [BTN_SIDE]}, {"keys": [BTN_LEFT], "rel": [REL_X]})
    for index, config in enumerate(configs):
        fake_evdev.InputDevice(f"/dev/input/event{40 + index}", name="Keyboard", phys=f"usb-5/input{index}",
                               **config)
    (row,) = _list_rows(sock_dir)
    assert row["kind"] == "keyboard"


def test_list_devices_reports_vendor(sock_dir, fake_evdev):
    """The vendor id is reported as four lowercase hex digits."""
    fake_evdev.InputDevice("/dev/input/event50", name="G502", vendor=LOGITECH_VENDOR, keys=[BTN_LEFT],
                           phys="usb-6/input0")
    (row,) = _list_rows(sock_dir)
    assert row["vendor"] == "046d"


def test_remaps_only_nodes_with_the_trigger(sock_dir, fake_evdev, naga_nodes):
    """One remapper per node: only the node emitting the trigger is grabbed; status has one row."""
    server = _server(sock_dir, _config(naga_nodes[0]))
    server.setup()
    try:
        assert [node.grabbed for node in naga_nodes] == [False, True, False]
        assert naga_nodes[0].closed and naga_nodes[2].closed and len(fake_evdev.UInput.instances) == 1
        (state,) = _ask(server, "status")["result"]["devices"]
        assert state["state"] == "active"
    finally:
        server.close()


def test_identity_state_takes_worst_node(sock_dir, fake_evdev):
    """Node states fold into one identity state: busy outranks active."""
    nodes = [fake_evdev.InputDevice(f"/dev/input/event{30 + index}", name="Pad", keys=[BTN_SIDE],
                                    phys=f"usb-4/input{index}") for index in range(2)]
    nodes[1].grab_error = 16  # EBUSY
    server = _server(sock_dir, _config(nodes[0]))
    server.setup()
    try:
        (state,) = _ask(server, "status")["result"]["devices"]
        assert state["state"] == "busy" and state["error"]
        assert nodes[0].grabbed
    finally:
        server.close()


def test_record_refused_when_every_node_is_grabbed_elsewhere(sock_dir, naga_nodes):
    """All nodes EBUSY on the probe grab: an explicit error and nothing left open."""
    for node in naga_nodes:
        node.grab_error = 16  # EBUSY
    server = _server(sock_dir, MacroConfig())
    server.setup()
    try:
        reply = _ask(server, "record_start", identity=devices.identity(naga_nodes[0]))
        assert not reply["ok"] and "grabbed exclusively" in reply["error"]
        assert server._handles == {} and all(node.closed for node in naga_nodes)
        assert _ask(server, "status")["result"]["recording"] is None
    finally:
        server.close()


def test_record_reports_partly_blocked_nodes(sock_dir, naga_nodes):
    """Some nodes grabbed elsewhere: recording goes ahead and says how many are blocked."""
    naga_nodes[0].grab_error = 16  # EBUSY
    server = _server(sock_dir, MacroConfig())
    server.setup()
    try:
        result = _ask(server, "record_start", identity=devices.identity(naga_nodes[0]))["result"]
        assert result["blocked_nodes"] == 1
        assert not any(node.grabbed for node in naga_nodes)
    finally:
        server.close()


def test_held_keys_skip_the_grab_probe(sock_dir, fake_evdev, naga_nodes):
    """With keys held the probe never grabs (it would hide the release), so nothing counts as blocked."""
    for node in naga_nodes:
        node.grab_error = 16  # EBUSY
        node.held_keys = [KEY_A]
    server = _server(sock_dir, MacroConfig())
    server.setup()
    try:
        result = _ask(server, "record_start", identity=devices.identity(naga_nodes[0]))["result"]
        assert "blocked_nodes" not in result
        assert not [call for call in fake_evdev.call_log if call[0] == "grab"]
    finally:
        server.close()


def test_engine_remapped_node_is_not_probed(sock_dir, mouse):
    """A node the engine grabs itself is not probed (the probe would only see our own grab)."""
    probed = []
    server = _server(sock_dir, _config(mouse), probe_grab=lambda dev: probed.append(dev) or True)
    server.setup()
    try:
        result = _ask(server, "record_start", identity=devices.identity(mouse))["result"]
        assert probed == [] and "blocked_nodes" not in result and mouse.grabbed
    finally:
        server.close()


def test_record_with_engine_remapped_node_and_other_nodes_busy(sock_dir, naga_nodes):
    """Every probed node busy but one node remapped by the engine: recording goes ahead via that node."""
    naga_nodes[0].grab_error = naga_nodes[2].grab_error = 16  # EBUSY
    server = _server(sock_dir, _config(naga_nodes[0]))
    server.setup()
    try:
        assert naga_nodes[1].grabbed
        result = _ask(server, "record_start", identity=devices.identity(naga_nodes[0]))["result"]
        assert result["blocked_nodes"] == 2
        naga_nodes[1].queue_events(make_event(EV_KEY, BTN_LEFT, 1, 1.0))
        server.run_once(0)
        assert _ask(server, "record_stop")["result"]["events"] == [["BTN_LEFT", 1, 0.0]]
        assert naga_nodes[1].grabbed and not naga_nodes[1].closed
    finally:
        server.close()


def test_key_watch_opens_matching_nodes_ungrabbed(sock_dir, keyboard, mouse):
    """Watched nodes open without grabbing, key-downs are polled by cursor, unwatching closes them."""
    server = _server(sock_dir, MacroConfig())
    server.setup()
    try:
        result = _ask(server, "key_watch", names=["keyb"])["result"]
        assert result["nodes"] == [keyboard.path] and not keyboard.grabbed and not keyboard.closed
        assert mouse.path not in server._handles
        keyboard.queue_events(make_event(EV_KEY, KEY_A, 1, 5.0), make_event(EV_KEY, KEY_A, 0, 5.1),
                              make_event(EV_KEY, KEY_A, 1, 6.0))
        server.run_once(0)
        assert _ask(server, "key_events", since=0)["result"] == {"events": [[KEY_A, 0, 5000], [KEY_A, 1, 6000]],
                                                                 "next": 2}
        assert _ask(server, "key_events", since=2)["result"] == {"events": [], "next": 2}
        assert _ask(server, "key_watch", names=[])["result"]["nodes"] == []
        assert keyboard.closed and server._handles == {}
    finally:
        server.close()


def test_key_watch_leaves_remapped_and_recording_nodes(sock_dir, mouse, keyboard):
    """Unwatching keeps a remapped (grabbed) node and a recording node open."""
    server = _server(sock_dir, _config(mouse))
    server.setup()
    try:
        assert _ask(server, "key_watch", names=["naga", "keyboard"])["ok"]
        assert mouse.grabbed
        assert _ask(server, "record_start", identity=devices.identity(keyboard))["ok"]
        assert _ask(server, "key_watch", names=[])["ok"]
        assert mouse.grabbed and not mouse.closed and not keyboard.closed
        _ask(server, "record_stop")
        assert keyboard.closed and not keyboard.grabbed
    finally:
        server.close()


def test_key_watch_keeps_node_open_after_record_stop(sock_dir, keyboard):
    """A watched node stays open when a recording on it stops."""
    server = _server(sock_dir, MacroConfig())
    server.setup()
    try:
        assert _ask(server, "key_watch", names=["Keyboard"])["ok"]
        assert _ask(server, "record_start", identity=devices.identity(keyboard))["ok"]
        _ask(server, "record_stop")
        assert not keyboard.closed and keyboard.path in server._handles
    finally:
        server.close()


@pytest.mark.parametrize("op, args", [
    ("key_watch", {}), ("key_watch", {"names": "Naga"}), ("key_watch", {"names": [1]}),
    ("key_events", {}), ("key_events", {"since": -1}), ("key_events", {"since": True}),
    ("key_events", {"since": "0"}),
])
def test_key_watch_rejects_bad_args(sock_dir, op, args):
    """Malformed key_watch/key_events arguments are command errors, not internal errors."""
    server = _server(sock_dir, MacroConfig())
    server.setup()
    try:
        reply = _ask(server, op, **args)
        assert not reply["ok"] and reply["error"] != "internal engine error; see the engine log"
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
