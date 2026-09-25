# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Grab one device, pass its events through a uinput clone, fire macros.

Wayland compositors read devices directly, so the only compositor-agnostic
way to swallow a trigger is an exclusive evdev grab plus a virtual clone
that re-emits every other event. The clone is created BEFORE grabbing: if
it cannot be created we never grab, so a failure can never leave the user
with a dead mouse or keyboard.

The grab is deferred while any key or button is held: grabbing then would
hide the release from the compositor and leave the key stuck down. Until
the grab happens nothing is forwarded to the clone (the compositor still
reads the real device, so forwarding would duplicate every event).
"""

import errno
import logging
from typing import Any, Callable, Iterable

from hueberry.macro_engine.devices import VIRTUAL_PREFIX
from hueberry.macro_engine.player import Player
from hueberry.macros import keycodes

logger = logging.getLogger(__name__)

STATE_IDLE = "idle"
STATE_INACTIVE = "inactive"
STATE_ACTIVE = "active"
STATE_WAITING = "waiting"
STATE_BUSY = "busy"
STATE_PERMISSION_DENIED = "permission_denied"
STATE_ERROR = "error"
STATE_STOPPED = "stopped"
UINPUT_MAX_NAME_LENGTH = 79  # UINPUT_MAX_NAME_SIZE (80) minus the terminating NUL
PERMISSION_ERRNOS = frozenset({errno.EACCES, errno.EPERM})


def clone_uinput(dev: Any, name: str) -> Any:
    """Create a uinput device with ``dev``'s capabilities."""
    import evdev  # lazy: optional dependency

    return evdev.UInput.from_device(dev, name=name)


def _uinput_errors() -> tuple[type[BaseException], ...]:
    import evdev  # lazy: optional dependency

    return (OSError, evdev.UInputError)


def state_for_error(exc: BaseException) -> str:
    code = getattr(exc, "errno", None)
    if code == errno.EBUSY:
        return STATE_BUSY
    if code in PERMISSION_ERRNOS:
        return STATE_PERMISSION_DENIED
    return STATE_ERROR


class DeviceRemapper:
    """Owns the grab and uinput clone of one device while it has enabled macros.

    ``state`` is one of the STATE_* constants; ``busy`` usually means another
    program (e.g. OpenRazer's macro mode) already grabbed the device.
    """

    def __init__(
        self,
        dev: Any,
        macros: Iterable,
        uinput_factory: Callable[[Any, str], Any] = clone_uinput,
        player_factory: Callable[[Any], Any] = Player,
    ) -> None:
        from evdev import ecodes  # lazy: optional dependency

        self.dev = dev
        self._macros = list(macros)
        self._uinput_factory = uinput_factory
        self._player_factory = player_factory
        self._ev_key = ecodes.EV_KEY
        self._triggers: dict[int, list] = {}
        self._clone: Any = None
        self._player: Any = None
        self._grabbed = False
        self.state = STATE_IDLE
        self.error: str | None = None

    @property
    def active(self) -> bool:
        """True while the device is grabbed and events are being remapped."""
        return self.state == STATE_ACTIVE

    @property
    def pending_grab(self) -> bool:
        """True while the clone exists but the grab waits for held keys to be released."""
        return self.state == STATE_WAITING

    def _resolve_triggers(self) -> dict[int, list]:
        triggers = {}
        for macro in self._macros:
            code = keycodes.code_for(macro.trigger) if macro.enabled else None
            if code is not None:
                triggers[code] = list(macro.steps)
        return triggers

    def _set_failure(self, state: str, message: str) -> bool:
        self.state = state
        self.error = message
        logger.warning("Remapper for %r: %s (%s)", self.dev.name, message, state)
        return False

    def start(self) -> bool:
        """Clone, then grab. Returns True when active; never grabs without a clone.

        With keys held the grab is deferred (state ``waiting``); call
        ``try_grab()`` again until it succeeds.
        """
        self._triggers = self._resolve_triggers()
        if not self._triggers:
            self.state = STATE_INACTIVE
            return False
        name = (VIRTUAL_PREFIX + self.dev.name)[:UINPUT_MAX_NAME_LENGTH]
        try:
            self._clone = self._uinput_factory(self.dev, name)
        except _uinput_errors() as exc:
            return self._set_failure(state_for_error(exc), f"cannot create uinput clone: {exc}")
        self._player = self._player_factory(self._clone)
        self.state = STATE_WAITING
        if not self.try_grab() and self.pending_grab:
            logger.info("Deferring grab of %r until held keys are released", self.dev.name)
        return self.active

    def try_grab(self) -> bool:
        """Grab a waiting device once no key is held. Returns True when active."""
        if self.state != STATE_WAITING:
            return self.active
        try:
            if self.dev.active_keys():
                return False
            self.dev.grab()
        except OSError as exc:
            self._close_clone()
            return self._set_failure(state_for_error(exc), f"cannot grab device: {exc}")
        self._grabbed = True
        self.state = STATE_ACTIVE
        self._discard_buffered()
        logger.info("Remapping %r (%d trigger(s))", self.dev.name, len(self._triggers))
        return True

    def _discard_buffered(self) -> None:
        """Drop events queued before the grab: the compositor already saw them."""
        try:
            for _event in self.dev.read():
                pass
        except (BlockingIOError, OSError):
            pass

    def handle(self, event: Any) -> None:
        """Swallow trigger events (playing on press); forward everything else."""
        if self.state != STATE_ACTIVE:
            return
        if event.type == self._ev_key and event.code in self._triggers:
            if event.value == keycodes.VALUE_PRESS:
                self._player.play(self._triggers[event.code])
            return
        try:
            with self._player.lock:
                self._clone.write(event.type, event.code, event.value)
        except OSError as exc:
            self._player.stop()
            self._release()
            self._set_failure(STATE_ERROR, f"uinput write failed, device released: {exc}")

    def _close_clone(self) -> None:
        clone, self._clone = self._clone, None
        if clone is None:
            return
        try:
            clone.close()
        except OSError as exc:
            logger.warning("Closing uinput clone failed: %s", exc)

    def _release(self) -> None:
        """Ungrab first (give the real device back), then drop the clone."""
        if self._grabbed:
            self._grabbed = False
            try:
                self.dev.ungrab()
            except OSError as exc:  # device already gone
                logger.warning("Ungrab of %r failed: %s", self.dev.name, exc)
        self._close_clone()

    def stop(self) -> None:
        """Stop playback, ungrab and close the clone; safe to call repeatedly."""
        if self._player is not None:
            self._player.stop()
        self._release()
        if self.state in (STATE_ACTIVE, STATE_WAITING):
            self.state = STATE_STOPPED
