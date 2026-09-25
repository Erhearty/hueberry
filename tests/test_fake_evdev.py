# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Sanity tests for the fake evdev test double."""

import errno

import pytest


def test_import_evdev_returns_fake(fake_evdev):
    """``import evdev`` inside tests yields the fake module."""
    import evdev
    from evdev import ecodes

    assert evdev is fake_evdev
    assert ecodes.KEY_A == 30 and ecodes.ecodes["BTN_LEFT"] == 0x110


def test_device_registry_grab_and_read(fake_evdev):
    """Registered devices reopen by path, grabs can fail, reads drain the queue."""
    dev = fake_evdev.InputDevice("/dev/input/event3", name="Mouse", keys=[0x110])
    assert fake_evdev.list_devices() == ["/dev/input/event3"]
    assert fake_evdev.InputDevice("/dev/input/event3") is dev
    dev.grab_error = errno.EBUSY
    with pytest.raises(OSError) as info:
        dev.grab()
    assert info.value.errno == errno.EBUSY
    with pytest.raises(BlockingIOError):
        dev.read()
    assert dev.active_keys() == []
    dev.held_keys = [0x110]
    assert dev.active_keys() == [0x110]
    event = fake_evdev.InputEvent(1, 0, 1, 0x110, 1)
    dev.queue_events(event)
    assert list(dev.read()) == [event]


def test_uinput_records_writes(fake_evdev):
    """UInput.from_device clones capabilities and records writes."""
    dev = fake_evdev.InputDevice("/dev/input/event4", name="Kbd", keys=[30])
    ui = fake_evdev.UInput.from_device(dev, name="clone")
    ui.write(1, 30, 1)
    ui.syn()
    ui.close()
    assert ui.events == {1: [30]}
    assert ui.writes == [(1, 30, 1), (0, 0, 0)] and ui.closed
