# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Plays macro steps into a uinput device on a worker thread.

Playback runs off the engine's event loop so a macro with delays never
stalls passthrough of the device's other keys. One Player exists per
grabbed device; a trigger pressed while its macro still plays is ignored
(no queueing, so a held or bouncing trigger cannot pile up input).
"""

import logging
import threading
from typing import Any, Callable, Iterable

from hueberry.macros import keycodes
from hueberry.macros.model import ACTION_PRESS, ACTION_RELEASE, ACTION_TAP, DelayStep

logger = logging.getLogger(__name__)

MS_PER_S = 1000
STOP_JOIN_TIMEOUT_S = 1.0
THREAD_NAME = "macro-player"
PRESS_ACTIONS = (ACTION_PRESS, ACTION_TAP)
RELEASE_ACTIONS = (ACTION_RELEASE, ACTION_TAP)


def start_daemon_thread(target: Callable[[], None]) -> threading.Thread:
    """Run ``target`` on a daemon thread (never blocks engine exit)."""
    thread = threading.Thread(target=target, name=THREAD_NAME, daemon=True)
    thread.start()
    return thread


class Player:
    """Writes macro steps to ``uinput``; ``sleep`` and ``start_thread`` are injectable.

    ``lock`` serialises whole reports (event + SYN) against the remapper's
    passthrough writes on the same uinput device.
    """

    def __init__(
        self,
        uinput: Any,
        sleep: Callable[[float], Any] | None = None,
        start_thread: Callable[[Callable[[], None]], Any] = start_daemon_thread,
    ) -> None:
        from evdev import ecodes  # lazy: optional dependency

        self._uinput = uinput
        self._ev_key = ecodes.EV_KEY
        self._cancel = threading.Event()
        self._sleep = sleep if sleep is not None else self._cancel.wait  # cancellable delays
        self._start_thread = start_thread
        self._state_lock = threading.Lock()
        self._playing = False
        self._thread: Any = None
        self.lock = threading.Lock()

    @property
    def playing(self) -> bool:
        """True while a macro is running."""
        with self._state_lock:
            return self._playing

    def play(self, steps: Iterable) -> bool:
        """Start playing ``steps``; returns False (ignored) if already playing."""
        with self._state_lock:
            if self._playing:
                logger.info("Macro trigger ignored: a macro is still playing")
                return False
            self._playing = True
        self._cancel.clear()
        steps = list(steps)
        self._thread = self._start_thread(lambda: self.run(steps))
        return True

    def run(self, steps: Iterable) -> None:
        """Play synchronously; always releases keys it left pressed."""
        pressed: set[int] = set()
        try:
            for step in steps:
                if self._cancel.is_set():
                    break
                self._perform(step, pressed)
        except OSError:
            logger.exception("Macro playback failed")
        finally:
            self._release(pressed)
            with self._state_lock:
                self._playing = False

    def _perform(self, step: Any, pressed: set[int]) -> None:
        if isinstance(step, DelayStep):
            self._sleep(step.ms / MS_PER_S)
            return
        code = keycodes.code_for(step.code)
        if code is None:
            logger.warning("Skipping unknown key %s", step.code)
            return
        if step.action in PRESS_ACTIONS:
            self._emit(code, keycodes.VALUE_PRESS)
            pressed.add(code)
        if step.action in RELEASE_ACTIONS:
            self._emit(code, keycodes.VALUE_RELEASE)
            pressed.discard(code)

    def _emit(self, code: int, value: int) -> None:
        with self.lock:
            self._uinput.write(self._ev_key, code, value)
            self._uinput.syn()

    def _release(self, pressed: set[int]) -> None:
        """Release still-held keys so a macro can never leave a key stuck down."""
        for code in sorted(pressed):
            try:
                self._emit(code, keycodes.VALUE_RELEASE)
            except OSError as exc:
                logger.warning("Could not release key %d: %s", code, exc)

    def stop(self, timeout: float = STOP_JOIN_TIMEOUT_S) -> None:
        """Cancel playback (between steps) and wait briefly for the worker."""
        self._cancel.set()
        thread = self._thread
        if isinstance(thread, threading.Thread) and thread is not threading.current_thread():
            thread.join(timeout)
