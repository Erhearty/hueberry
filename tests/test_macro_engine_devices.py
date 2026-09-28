# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for engine device discovery and permission checks."""

import errno
import os

from hueberry.macro_engine import devices


def _mouse(fake_evdev, path="/dev/input/event5", **kwargs):
    config = {"name": "Razer Basilisk", "vendor": 0x1532, "product": 0x0084,
              "keys": [0x110, 0x113], "phys": "usb-0000:00:14.0-2/input0", "uniq": ""}
    config.update(kwargs)
    return fake_evdev.InputDevice(path, **config)


def test_identity_prefers_uniq_over_phys(fake_evdev):
    """vendor:product:name:uniq, falling back to phys."""
    assert devices.identity(_mouse(fake_evdev)) == "1532:0084:Razer Basilisk:usb-0000:00:14.0-2"
    serial = _mouse(fake_evdev, "/dev/input/event6", uniq="SN123")
    assert devices.identity(serial) == "1532:0084:Razer Basilisk:SN123"


def test_nodes_of_one_device_share_an_identity(fake_evdev):
    """Three nodes differing only in /inputN are one physical device; other ports stay distinct."""
    nodes = [_mouse(fake_evdev, f"/dev/input/event{10 + index}", phys=f"usb-0000:00:14.0-2/input{index}")
             for index in range(3)]
    assert {devices.identity(node) for node in nodes} == {"1532:0084:Razer Basilisk:usb-0000:00:14.0-2"}
    other = _mouse(fake_evdev, "/dev/input/event20", phys="usb-0000:00:14.0-3/input0")
    assert devices.identity(other) != devices.identity(nodes[0])
    assert len({e.identity for e in devices.discover() if e.name == "Razer Basilisk"}) == 2


def test_discover_skips_virtual_clones_and_closes(fake_evdev):
    """Our own uinput clones are excluded; every opened device is closed."""
    mouse = _mouse(fake_evdev)
    clone = fake_evdev.InputDevice("/dev/input/event9", name=devices.VIRTUAL_PREFIX + "Razer Basilisk",
                                   keys=[0x110])
    power = fake_evdev.InputDevice("/dev/input/event0", name="Power LED", keys=[])
    entries = devices.discover()
    assert [(e.path, e.name, e.has_keys) for e in entries] == [
        ("/dev/input/event0", "Power LED", False),
        ("/dev/input/event5", "Razer Basilisk", True),
    ]
    assert entries[1].identity == devices.identity(mouse)
    assert mouse.closed and clone.closed and power.closed


def test_discover_uses_injected_functions_and_skips_open_errors(fake_evdev):
    """Injected list/open are used; devices failing to open are skipped."""
    mouse = _mouse(fake_evdev)

    def _open(path):
        if path == "/dev/input/gone":
            raise OSError(errno.ENODEV, "No such device")
        return mouse

    entries = devices.discover(list_devices=lambda: ["/dev/input/gone", mouse.path], open=_open)
    assert [e.path for e in entries] == [mouse.path]


def test_device_kind(fake_evdev):
    """REL_X plus BTN_LEFT is a mouse; KEY_A a keyboard; anything else other."""
    ecodes = fake_evdev.ecodes
    pointer = _mouse(fake_evdev, keys=[ecodes.BTN_LEFT], rel=[ecodes.REL_X])
    assert devices.device_kind(pointer) == devices.KIND_MOUSE
    keyboard = _mouse(fake_evdev, "/dev/input/event6", keys=[ecodes.KEY_A])
    assert devices.device_kind(keyboard) == devices.KIND_KEYBOARD
    buttons_only = _mouse(fake_evdev, "/dev/input/event7")
    assert devices.device_kind(buttons_only) == devices.KIND_OTHER


def test_probe_foreign_grab(fake_evdev):
    """EBUSY means grabbed elsewhere; a successful probe is undone; held keys skip it; other errors are not busy."""
    mouse = _mouse(fake_evdev)
    assert not devices.probe_foreign_grab(mouse)
    assert mouse.grab_calls == 1 and mouse.ungrab_calls == 1 and not mouse.grabbed
    mouse.grab_error = errno.EBUSY
    assert devices.probe_foreign_grab(mouse)
    mouse.held_keys = [0x110]
    assert not devices.probe_foreign_grab(mouse)
    mouse.held_keys = []
    mouse.grab_error = errno.EIO
    assert not devices.probe_foreign_grab(mouse)
    assert mouse.grab_calls == 1 and ("grab", mouse.path) in fake_evdev.call_log


def test_check_permissions_reports_uinput_and_unreadable():
    """uinput needs read+write; unreadable event nodes are listed."""
    allowed = {("/dev/uinput", os.R_OK | os.W_OK), ("/dev/input/event1", os.R_OK)}
    report = devices.check_permissions(
        access=lambda path, mode: (path, mode) in allowed,
        list_nodes=lambda: ["/dev/input/event1", "/dev/input/event2"],
    )
    assert report.uinput_ok
    assert report.unreadable_inputs == ("/dev/input/event2",)
    denied = devices.check_permissions(access=lambda path, mode: False, list_nodes=lambda: [])
    assert not denied.uinput_ok and denied.unreadable_inputs == ()
