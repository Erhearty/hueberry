# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the Erheart animator (passive: ``step()`` is called directly)."""

import threading
import time

import pytest

from hueberry.backend import animator, effects, presets
from hueberry.backend.animator import Animator
from hueberry.backend.effects import Preset
from hueberry.backend.led_layout import DeviceShape, group_layout

MATRIX_CAPS = ("lighting", "lighting_static", "lighting_led_matrix")
ZONE_CAPS = ("lighting", "lighting_static")
KBD_SERIAL = "KBD0001"
MOUSE_SERIAL = "MOUSE0001"
THREAD_DEADLINE_S = 2.0
POLL_S = 0.01
TEST_FPS = 100
PAD_SERIAL = "PAD0001"
PINK = (255, 58, 130)
RED = (255, 0, 0)


@pytest.fixture
def anim():
    return Animator(start_thread=False)


def _static_calls(calls):
    return [args for name, args in calls if name == "static"]


def _drawn(advanced, index=-1):
    """A drawn matrix snapshot as rows of colours, like an effects frame."""
    draw = advanced.draws[index]
    return tuple(tuple(draw[row, col] for col in range(advanced.cols))
                 for row in range(advanced.rows))


def _kbd(make_device, serial=KBD_SERIAL):
    return make_device(serial=serial, capabilities=MATRIX_CAPS)


def _mouse(make_device, serial=MOUSE_SERIAL):
    return make_device(serial=serial, capabilities=ZONE_CAPS)


def _custom(effect=effects.EFFECT_WAVE, palette=(PINK, (0, 0, 255))):
    return Preset(key="custom", label="Custom", effect=effect, palette=palette, speed=6.0)


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


def test_static_preset_paints_first_colour_once(anim, make_device):
    kbd, mouse = _kbd(make_device), _mouse(make_device)
    static = _custom(effect=effects.EFFECT_STATIC)
    anim.start(kbd, static)
    anim.start(mouse, static)
    anim.step()
    anim.step()
    (frame,) = kbd.fx.advanced.draws
    assert set(frame.values()) == {PINK}
    assert _static_calls(mouse.fx.calls) == [PINK]


def test_group_shares_one_phase_and_layout(anim, make_device):
    kbd, mouse = _kbd(make_device), _mouse(make_device)
    assert anim.start_group([kbd, mouse], presets.ERHEART) == [KBD_SERIAL, MOUSE_SERIAL]
    anim.step()
    anim.step()
    advanced = kbd.fx.advanced
    layout = group_layout([DeviceShape.of_matrix(KBD_SERIAL, advanced.rows, advanced.cols),
                           DeviceShape.of_zones(MOUSE_SERIAL)])
    second = effects.advance_phase(presets.ERHEART, 0.0, presets.FPS)
    for index, phase in enumerate((0.0, second)):
        frames = effects.render_run(presets.ERHEART, layout, phase)
        assert _drawn(advanced, index) == frames[KBD_SERIAL]
        assert _static_calls(mouse.fx.calls)[index] == frames[MOUSE_SERIAL][0][0]
    assert [(run.serials, run.grouped) for run in anim.runs()] == [
        ((KBD_SERIAL, MOUSE_SERIAL), True)]


def test_start_group_returns_started_serials(anim, make_device):
    kbd, mouse = _kbd(make_device), _mouse(make_device)
    spectrum = make_device(serial=PAD_SERIAL, capabilities=("lighting", "lighting_spectrum"))
    started = anim.start_group([mouse, spectrum, None, kbd, mouse], presets.ERHEART)
    assert started == [MOUSE_SERIAL, KBD_SERIAL]
    assert anim.start_group([spectrum], presets.ERHEART) == []
    assert anim.start_group([], presets.ERHEART) == []


def test_starting_a_group_member_alone_moves_it_out(anim, make_device):
    kbd, mouse, mouse2 = _kbd(make_device), _mouse(make_device), _mouse(make_device, PAD_SERIAL)
    anim.start_group([kbd, mouse, mouse2], presets.ERHEART)
    assert anim.start(mouse, _custom())
    runs = {run.preset.key: run for run in anim.runs()}
    assert runs[presets.ERHEART.key].serials == (KBD_SERIAL, PAD_SERIAL)
    assert runs["custom"].serials == (MOUSE_SERIAL,) and not runs["custom"].grouped
    anim.step()
    advanced = kbd.fx.advanced
    layout = group_layout([DeviceShape.of_matrix(KBD_SERIAL, advanced.rows, advanced.cols),
                           DeviceShape.of_zones(PAD_SERIAL)])
    frames = effects.render_run(presets.ERHEART, layout, 0.0)
    assert _drawn(advanced) == frames[KBD_SERIAL]
    assert _static_calls(mouse2.fx.calls) == [frames[PAD_SERIAL][0][0]]
    assert anim.running_preset(MOUSE_SERIAL) == "custom"


def test_update_preset_changes_next_frame_and_keeps_phase(anim, make_device):
    kbd, mouse = _kbd(make_device), _mouse(make_device)
    anim.start(kbd, _custom(effect=effects.EFFECT_STATIC))
    anim.start(mouse, presets.ERHEART)
    anim.step()
    assert set(kbd.fx.advanced.draws[0].values()) == {PINK}
    edited = _custom(effect=effects.EFFECT_STATIC, palette=(RED,))
    assert anim.update_preset(edited) == 1
    assert anim.update_preset(_custom().with_changes(key="unknown")) == 0
    anim.step()
    assert set(kbd.fx.advanced.draws[1].values()) == {RED}
    assert anim.runs()[0].preset == edited
    wave = _custom(palette=(RED,))
    anim.update_preset(wave)
    anim.step()
    phase = effects.advance_phase(wave, effects.advance_phase(edited, 0.0, presets.FPS),
                                  presets.FPS)
    layout = group_layout([DeviceShape.of_matrix(KBD_SERIAL, kbd.fx.advanced.rows,
                                                 kbd.fx.advanced.cols)])
    assert _drawn(kbd.fx.advanced) == effects.render_run(wave, layout, phase)[KBD_SERIAL]


def test_in_flight_frame_of_old_static_preset_does_not_hide_the_new_one(anim, make_device):
    kbd = _kbd(make_device)
    old = _custom(effect=effects.EFFECT_STATIC)
    anim.start(kbd, old)
    run = anim._runs[0]
    targets, layout = list(run.targets), run.layout  # snapshot taken by an in-flight step
    new = _custom(effect=effects.EFFECT_STATIC, palette=(RED,))
    assert anim.update_preset(new) == 1
    animator._render_run(old, targets, layout, animator.START_PHASE)  # the frame lands late
    assert set(kbd.fx.advanced.draws[-1].values()) == {PINK}
    anim.step()
    assert set(kbd.fx.advanced.draws[-1].values()) == {RED}
    anim.step()
    assert len(kbd.fx.advanced.draws) == 2


@pytest.mark.parametrize("empty", ["rows", "cols"])
def test_empty_matrix_falls_back_to_zones(anim, make_device, empty):
    kbd = _kbd(make_device)
    setattr(kbd.fx.advanced, empty, 0)
    assert anim.start(kbd, presets.ERHEART)
    assert anim.start_group([kbd], presets.ERHEART) == [KBD_SERIAL]
    anim.step()
    assert kbd.fx.advanced.draws == []
    assert _static_calls(kbd.fx.calls)


def test_stopping_one_group_member_keeps_the_others(anim, make_device):
    kbd, mouse = _kbd(make_device), _mouse(make_device)
    anim.start_group([kbd, mouse], presets.ERHEART)
    anim.step()
    assert anim.stop(MOUSE_SERIAL)
    assert anim.is_running(KBD_SERIAL) and not anim.is_running(MOUSE_SERIAL)
    assert [run.serials for run in anim.runs()] == [(KBD_SERIAL,)]
    anim.step()
    assert len(_static_calls(mouse.fx.calls)) == 1
    rows, cols = kbd.fx.advanced.rows, kbd.fx.advanced.cols
    offset = presets.next_offset(0.0)
    assert _drawn(kbd.fx.advanced)[0][0] == presets.matrix_colour(0, 0, rows, cols, offset)
    assert kbd.fx.advanced.restore_calls == 0


def test_running_preset(anim, make_device):
    kbd, mouse = _kbd(make_device), _mouse(make_device)
    assert anim.running_preset(KBD_SERIAL) is None
    anim.start(kbd)
    anim.start_group([mouse], _custom())
    assert anim.running_preset(KBD_SERIAL) == presets.ERHEART.key
    assert anim.running_preset(MOUSE_SERIAL) == "custom"
    anim.stop(KBD_SERIAL)
    assert anim.running_preset(KBD_SERIAL) is None


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
