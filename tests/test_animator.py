# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the Erheart animator (passive: ``step()`` is called directly)."""

import threading
import time

import pytest

from hueberry.backend import animator, presets
from hueberry.backend.animator import Animator

MATRIX_CAPS = ("lighting", "lighting_static", "lighting_led_matrix")
ZONE_CAPS = ("lighting", "lighting_static")
OVERRIDE_SERIAL = "ST2433V02000015"
KBD_SERIAL = "KBD0001"
MOUSE_SERIAL = "MOUSE0001"
THREAD_DEADLINE_S = 2.0
POLL_S = 0.01
TEST_FPS = 100


@pytest.fixture
def anim():
    return Animator(start_thread=False)


def _static_calls(calls):
    return [args for name, args in calls if name == "static"]


def test_matrix_device_gets_per_key_wave(anim, make_device):
    dev = make_device(serial=KBD_SERIAL, capabilities=MATRIX_CAPS)
    assert anim.start(dev)
    assert anim.is_running(KBD_SERIAL)
    anim.step()
    advanced = dev.fx.advanced
    (frame,) = advanced.draws
    assert len(frame) == advanced.rows * advanced.cols
    assert frame[2, 5] == presets.matrix_colour(2, 5, advanced.rows, advanced.cols, 0.0)
    assert dev.fx.calls == []


def test_offset_advances_and_devices_share_it(anim, make_device):
    kbd = make_device(serial=KBD_SERIAL, capabilities=MATRIX_CAPS)
    mouse = make_device(serial=MOUSE_SERIAL, capabilities=ZONE_CAPS)
    anim.start(kbd)
    anim.step()
    anim.start(mouse)
    anim.step()
    offset = presets.next_offset(0.0)
    rows, cols = kbd.fx.advanced.rows, kbd.fx.advanced.cols
    assert kbd.fx.advanced.draws[1][0, 0] == presets.matrix_colour(0, 0, rows, cols, offset)
    assert _static_calls(mouse.fx.calls) == [presets.zone_colour(offset)]


def test_zone_device_animates_every_static_zone(anim, make_device):
    dev = make_device(serial=MOUSE_SERIAL, capabilities=ZONE_CAPS + ("lighting_logo_static",),
                      zones=("logo",))
    anim.start(dev)
    anim.step()
    anim.step()
    expected = [presets.zone_colour(0.0), presets.zone_colour(presets.next_offset(0.0))]
    assert _static_calls(dev.fx.calls) == expected
    assert _static_calls(dev.fx.misc.logo.calls) == expected


def test_serial_override_paints_fixed_colour_once(anim, make_device):
    dev = make_device(serial=OVERRIDE_SERIAL, capabilities=MATRIX_CAPS)
    anim.start(dev)
    anim.step()
    anim.step()
    assert _static_calls(dev.fx.calls) == [presets.SERIAL_OVERRIDES[OVERRIDE_SERIAL]]
    assert dev.fx.advanced.draws == []


def test_unsupported_device_is_not_started(anim, make_device):
    dev = make_device(serial=MOUSE_SERIAL, capabilities=("lighting", "lighting_spectrum"))
    assert not animator.supports(dev)
    assert not anim.start(dev)
    assert not anim.is_running()


def test_stop_restores_matrix(anim, make_device):
    dev = make_device(serial=KBD_SERIAL, capabilities=MATRIX_CAPS)
    anim.start(dev)
    assert anim.stop(KBD_SERIAL)
    assert dev.fx.advanced.restore_calls == 1
    assert not anim.is_running(KBD_SERIAL)
    assert not anim.stop(KBD_SERIAL)
    anim.start(dev)
    anim.stop(KBD_SERIAL, restore=False)
    assert dev.fx.advanced.restore_calls == 1


def test_stopped_target_is_not_rendered_and_restore_follows_last_draw(anim, make_device):
    dev = make_device(serial=KBD_SERIAL, capabilities=MATRIX_CAPS)
    advanced = dev.fx.advanced
    log = []
    advanced.draw = lambda: log.append("draw")
    advanced.restore = lambda: log.append("restore")
    anim.start(dev)
    anim.step()
    assert anim.stop(KBD_SERIAL, restore=True)
    anim.step()
    assert log == ["draw", "restore"]


def test_blocked_render_does_not_block_is_running_or_start(anim, make_device):
    kbd = make_device(serial=KBD_SERIAL, capabilities=MATRIX_CAPS)
    mouse = make_device(serial=MOUSE_SERIAL, capabilities=ZONE_CAPS)
    drawing, release = threading.Event(), threading.Event()

    def blocking_draw():
        drawing.set()
        release.wait(THREAD_DEADLINE_S)

    kbd.fx.advanced.draw = blocking_draw
    anim.start(kbd)
    stepper = threading.Thread(target=anim.step, daemon=True)
    results = []
    checker = threading.Thread(
        target=lambda: results.append((anim.is_running(KBD_SERIAL), anim.start(mouse))),
        daemon=True)
    try:
        stepper.start()
        assert drawing.wait(THREAD_DEADLINE_S)
        checker.start()
        checker.join(THREAD_DEADLINE_S)
        assert results == [(True, True)]
    finally:
        release.set()
    stepper.join(THREAD_DEADLINE_S)
    assert not stepper.is_alive()
    assert anim.is_running(MOUSE_SERIAL)


def _failing_draw(message_or_exc):
    def draw():
        raise message_or_exc
    return draw


def test_stale_error_pauses_until_refresh(anim, make_device):
    dev = make_device(serial=KBD_SERIAL, capabilities=MATRIX_CAPS)
    anim.start(dev)
    calls = []

    def stale_draw():
        calls.append(1)
        raise RuntimeError("org.freedesktop.DBus.Error.NoReply")

    dev.fx.advanced.draw = stale_draw
    anim.step()
    anim.step()
    assert anim.is_running(KBD_SERIAL)
    assert len(calls) == 1
    new_dev = make_device(serial=KBD_SERIAL, capabilities=MATRIX_CAPS)
    anim.refresh([new_dev])
    anim.step()
    assert len(new_dev.fx.advanced.draws) == 1


def test_not_ready_error_keeps_target(anim, make_device):
    dev = make_device(serial=KBD_SERIAL, capabilities=MATRIX_CAPS)
    anim.start(dev)
    dev.fx.advanced.draw = _failing_draw(PermissionError("[Errno 13] denied"))
    anim.step()
    assert anim.is_running(KBD_SERIAL)


def test_other_error_keeps_target(anim, make_device):
    dev = make_device(serial=KBD_SERIAL, capabilities=MATRIX_CAPS)
    anim.start(dev)
    dev.fx.advanced.draw = _failing_draw(ValueError("bad"))
    anim.step()
    anim.step()
    assert anim.is_running(KBD_SERIAL)


def test_refresh_rebinds_and_drops(anim, make_device):
    old_kbd = make_device(serial=KBD_SERIAL, capabilities=MATRIX_CAPS)
    anim.start(old_kbd)
    anim.start(make_device(serial=MOUSE_SERIAL, capabilities=ZONE_CAPS))
    new_kbd = make_device(serial=KBD_SERIAL, capabilities=MATRIX_CAPS)
    anim.refresh([new_kbd])
    assert anim.is_running(KBD_SERIAL)
    assert not anim.is_running(MOUSE_SERIAL)
    anim.step()
    assert old_kbd.fx.advanced.draws == []
    assert len(new_kbd.fx.advanced.draws) == 1
    anim.refresh([])
    assert not anim.is_running()


def test_shared_animator_is_a_singleton():
    assert animator.shared_animator() is animator.shared_animator()


def test_thread_animates_and_shutdown_restores(make_device):
    anim = Animator(fps=TEST_FPS)
    dev = make_device(serial=KBD_SERIAL, capabilities=MATRIX_CAPS)
    anim.start(dev)
    deadline = time.monotonic() + THREAD_DEADLINE_S
    while not dev.fx.advanced.draws and time.monotonic() < deadline:
        time.sleep(POLL_S)
    assert dev.fx.advanced.draws
    thread = anim._thread
    anim.shutdown()
    assert thread is not None and not thread.is_alive()
    assert not anim.is_running()
    assert dev.fx.advanced.restore_calls == 1
