# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the device remapper: grab ordering, fallbacks, passthrough, triggers."""

import errno

import pytest
from fake_evdev import make_event

from hueberry.macro_engine import remapper as remapper_mod
from hueberry.macro_engine.remapper import DeviceRemapper
from hueberry.macros.model import REPEAT_ONCE, REPEAT_TIMES, REPEAT_TOGGLE, KeyStep, Macro

EV_SYN, EV_KEY, EV_REL = 0, 1, 2
BTN_LEFT, BTN_SIDE, BTN_EXTRA = 0x110, 0x113, 0x114


class _FakePlayer:
    """Records play()/stop() calls; stays 'playing' until stop(); ignores play while playing."""

    def __init__(self, uinput):
        import threading

        self.uinput = uinput
        self.lock = threading.Lock()
        self.played = []
        self.calls = []
        self.stopped = 0
        self.playing = False
        self.current = None

    def play(self, steps, iterations=1, key=None):
        if self.playing:
            return False
        self.played.append(steps)
        self.calls.append((steps, iterations, key))
        self.playing, self.current = True, key
        return True

    def stop(self):
        self.stopped += 1
        self.playing, self.current = False, None


@pytest.fixture
def mouse(fake_evdev):
    return fake_evdev.InputDevice("/dev/input/event7", name="Razer Naga", keys=[BTN_LEFT, BTN_SIDE, BTN_EXTRA])


def _remapper(mouse, *macros):
    macros = macros or (Macro("m1", "Hi", True, "BTN_SIDE", [KeyStep("KEY_H"), KeyStep("KEY_I")]),)
    return DeviceRemapper(mouse, macros, player_factory=_FakePlayer)


def test_clone_created_before_grab(fake_evdev, mouse):
    """The uinput clone exists before the grab, and is named with the virtual prefix."""
    remapper = _remapper(mouse)
    assert remapper.start() and remapper.state == "active"
    assert fake_evdev.call_log == [("uinput", "hueberry-virtual:Razer Naga"), ("grab", mouse.path)]
    assert mouse.grabbed


@pytest.mark.parametrize("code, state", [
    (errno.EBUSY, "busy"), (errno.EACCES, "permission_denied"), (errno.EIO, "error"),
])
def test_grab_failures_close_clone(fake_evdev, mouse, code, state):
    """EBUSY/EACCES/other grab failures set a state and close the clone."""
    mouse.grab_error = code
    remapper = _remapper(mouse)
    assert not remapper.start()
    assert remapper.state == state and remapper.error
    (clone,) = fake_evdev.UInput.instances
    assert clone.closed and not mouse.grabbed


def test_uinput_failure_never_grabs(fake_evdev, mouse):
    """If the clone cannot be created the device is not grabbed."""
    fake_evdev.UInput.create_error = OSError(errno.EACCES, "Permission denied")
    remapper = _remapper(mouse)
    assert not remapper.start()
    assert remapper.state == "permission_denied"
    assert mouse.grab_calls == 0 and ("grab", mouse.path) not in fake_evdev.call_log


def test_uinput_error_type_is_handled(fake_evdev, mouse):
    """evdev.UInputError maps to the error state."""
    fake_evdev.UInput.create_error = fake_evdev.UInputError("no uinput")
    remapper = _remapper(mouse)
    assert not remapper.start() and remapper.state == "error"


def test_only_enabled_macros_count(fake_evdev, mouse):
    """With no enabled macros the device is never grabbed."""
    remapper = _remapper(mouse, Macro("m1", "Off", False, "BTN_SIDE", [KeyStep("KEY_A")]))
    assert not remapper.start()
    assert remapper.state == "inactive"
    assert fake_evdev.call_log == []


def test_node_without_trigger_code_stays_inactive(fake_evdev):
    """A node that cannot emit the trigger (another interface of the device) is never cloned or grabbed."""
    keyboard_node = fake_evdev.InputDevice("/dev/input/event9", name="Razer Naga", keys=[30])
    remapper = _remapper(keyboard_node)
    assert not remapper.start()
    assert remapper.state == "inactive" and not remapper.pending_grab
    assert keyboard_node.grab_calls == 0 and fake_evdev.call_log == [] and fake_evdev.UInput.instances == []


def test_only_triggers_the_node_emits_are_armed(fake_evdev):
    """Triggers missing from the node's EV_KEY capabilities pass through instead of being swallowed."""
    dev = fake_evdev.InputDevice("/dev/input/event9", name="Razer Naga", keys=[BTN_LEFT, BTN_SIDE])
    remapper = _remapper(dev, Macro("m1", "Hi", True, "BTN_SIDE", [KeyStep("KEY_H")]),
                         Macro("m2", "Ex", True, "BTN_EXTRA", [KeyStep("KEY_B")]))
    assert remapper.start()
    assert set(remapper._triggers) == {BTN_SIDE}


def test_passthrough_and_trigger_dispatch(fake_evdev, mouse):
    """Trigger press plays and is swallowed (as are release/repeat); others pass through."""
    remapper = _remapper(mouse, Macro("m1", "Hi", True, "BTN_SIDE", [KeyStep("KEY_H")]),
                         Macro("m2", "Off", False, "BTN_EXTRA", [KeyStep("KEY_B")]))
    remapper.start()
    (clone,) = fake_evdev.UInput.instances
    for event in [make_event(EV_KEY, BTN_SIDE, 1), make_event(EV_KEY, BTN_SIDE, 2),
                  make_event(EV_KEY, BTN_SIDE, 0), make_event(EV_KEY, BTN_LEFT, 1),
                  make_event(EV_REL, 0, 3), make_event(EV_KEY, BTN_EXTRA, 1),
                  make_event(EV_SYN, 0, 0)]:
        remapper.handle(event)
    assert clone.writes == [(EV_KEY, BTN_LEFT, 1), (EV_REL, 0, 3), (EV_KEY, BTN_EXTRA, 1), (EV_SYN, 0, 0)]
    player = remapper._player
    assert player.played == [[KeyStep("KEY_H")]]


def _press(remapper, code):
    remapper.handle(make_event(EV_KEY, code, 1))
    remapper.handle(make_event(EV_KEY, code, 0))


def _repeating(mode, count=1, trigger="BTN_SIDE", macro_id="m1"):
    return Macro(macro_id, "Loop", True, trigger, [KeyStep("KEY_H")], repeat_mode=mode, repeat_count=count)


@pytest.mark.parametrize("mode, count, iterations", [
    (REPEAT_ONCE, 5, 1), (REPEAT_TIMES, 4, 4), (REPEAT_TOGGLE, 1, None),
])
def test_trigger_plays_with_repeat_iterations(fake_evdev, mouse, mode, count, iterations):
    """once plays one iteration, times N passes N, toggle loops (None); the trigger code is the key."""
    remapper = _remapper(mouse, _repeating(mode, count))
    remapper.start()
    _press(remapper, BTN_SIDE)
    assert remapper._player.calls == [([KeyStep("KEY_H")], iterations, BTN_SIDE)]


@pytest.mark.parametrize("mode", [REPEAT_TOGGLE, REPEAT_TIMES])
def test_repress_stops_a_loop(fake_evdev, mouse, mode):
    """A second press of a playing toggle / N-times trigger stops it; a third starts it again."""
    remapper = _remapper(mouse, _repeating(mode, 3))
    remapper.start()
    player = remapper._player
    _press(remapper, BTN_SIDE)
    assert player.playing and player.stopped == 0
    _press(remapper, BTN_SIDE)
    assert not player.playing and player.stopped == 1 and len(player.calls) == 1
    _press(remapper, BTN_SIDE)
    assert player.playing and len(player.calls) == 2


def test_repress_of_once_macro_does_not_stop_it(fake_evdev, mouse):
    """Re-pressing a still-playing once macro is ignored, not a stop."""
    remapper = _remapper(mouse, _repeating(REPEAT_ONCE))
    remapper.start()
    _press(remapper, BTN_SIDE)
    _press(remapper, BTN_SIDE)
    player = remapper._player
    assert player.stopped == 0 and player.playing and len(player.calls) == 1


def test_other_trigger_while_playing_is_ignored(fake_evdev, mouse):
    """A different trigger during a loop neither stops it nor starts its own macro."""
    remapper = _remapper(mouse, _repeating(REPEAT_TOGGLE),
                         _repeating(REPEAT_TOGGLE, trigger="BTN_EXTRA", macro_id="m2"))
    remapper.start()
    _press(remapper, BTN_SIDE)
    _press(remapper, BTN_EXTRA)
    player = remapper._player
    assert player.stopped == 0 and player.current == BTN_SIDE and len(player.calls) == 1
    (clone,) = fake_evdev.UInput.instances
    assert clone.writes == []


def test_write_failure_ungrabs(fake_evdev, mouse):
    """A clone write error releases the grab and enters the error state."""
    remapper = _remapper(mouse)
    remapper.start()
    (clone,) = fake_evdev.UInput.instances
    clone.write_error = OSError(errno.ENODEV, "No such device")
    remapper.handle(make_event(EV_KEY, BTN_LEFT, 1))
    assert remapper.state == "error"
    assert not mouse.grabbed and mouse.ungrab_calls == 1 and clone.closed
    assert remapper._player.stopped == 1
    remapper.handle(make_event(EV_KEY, BTN_LEFT, 0))
    assert mouse.ungrab_calls == 1


def test_held_key_defers_grab(fake_evdev, mouse):
    """With a button held the clone is made but the grab waits; nothing is forwarded meanwhile."""
    mouse.held_keys = [BTN_LEFT]
    remapper = _remapper(mouse)
    assert not remapper.start()
    assert remapper.state == "waiting" and remapper.pending_grab and not mouse.grabbed
    (clone,) = fake_evdev.UInput.instances
    remapper.handle(make_event(EV_KEY, BTN_LEFT, 0))
    remapper.handle(make_event(EV_KEY, BTN_SIDE, 1))
    assert clone.writes == [] and remapper._player.played == []
    assert not remapper.try_grab() and not mouse.grabbed
    mouse.held_keys = []
    assert remapper.try_grab() and remapper.state == "active" and mouse.grabbed
    assert fake_evdev.call_log == [("uinput", "hueberry-virtual:Razer Naga"), ("grab", mouse.path)]
    assert remapper.try_grab() and mouse.grab_calls == 1


def test_deferred_grab_discards_buffered_events(fake_evdev, mouse):
    """Events queued before the grab already reached the compositor; they are dropped, not forwarded."""
    mouse.held_keys = [BTN_LEFT]
    remapper = _remapper(mouse)
    remapper.start()
    mouse.held_keys = []
    mouse.queue_events(make_event(EV_KEY, BTN_LEFT, 0), make_event(EV_SYN, 0, 0))
    assert remapper.try_grab()
    (clone,) = fake_evdev.UInput.instances
    assert clone.writes == []
    with pytest.raises(BlockingIOError):
        mouse.read()


def test_deferred_grab_failure_closes_clone(fake_evdev, mouse):
    """A grab that fails on retry closes the clone and reports the state."""
    mouse.held_keys = [BTN_LEFT]
    remapper = _remapper(mouse)
    remapper.start()
    mouse.held_keys = []
    mouse.grab_error = errno.EBUSY
    assert not remapper.try_grab()
    (clone,) = fake_evdev.UInput.instances
    assert remapper.state == "busy" and clone.closed and not remapper.pending_grab


def test_stop_while_waiting(fake_evdev, mouse):
    """stop() on a waiting remapper closes the clone without ungrabbing."""
    mouse.held_keys = [BTN_SIDE]
    remapper = _remapper(mouse)
    remapper.start()
    remapper.stop()
    (clone,) = fake_evdev.UInput.instances
    assert remapper.state == "stopped" and clone.closed and mouse.ungrab_calls == 0


def test_stop_is_idempotent(fake_evdev, mouse):
    """stop() ungrabs and closes once, however often it is called."""
    remapper = _remapper(mouse)
    remapper.start()
    (clone,) = fake_evdev.UInput.instances
    remapper.stop()
    remapper.stop()
    assert remapper.state == "stopped"
    assert mouse.ungrab_calls == 1 and clone.close_calls == 1 and not mouse.grabbed


def test_long_names_are_truncated(fake_evdev):
    """uinput names stay within the kernel limit."""
    dev = fake_evdev.InputDevice("/dev/input/event8", name="X" * 200, keys=[BTN_SIDE])
    _remapper(dev).start()
    (clone,) = fake_evdev.UInput.instances
    assert len(clone.name) == remapper_mod.UINPUT_MAX_NAME_LENGTH


def test_default_player_plays_through_clone(fake_evdev, mouse):
    """With the real Player, a trigger press writes the macro into the clone."""
    remapper = DeviceRemapper(mouse, [Macro("m1", "A", True, "BTN_SIDE", [KeyStep("KEY_A")])])
    remapper.start()
    remapper._player._start_thread = lambda target: target()
    remapper.handle(make_event(EV_KEY, BTN_SIDE, 1))
    (clone,) = fake_evdev.UInput.instances
    assert clone.writes == [(EV_KEY, 30, 1), (EV_SYN, 0, 0), (EV_KEY, 30, 0), (EV_SYN, 0, 0)]
