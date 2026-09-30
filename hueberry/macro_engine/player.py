# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Plays macro steps into a uinput device on a worker thread.

Playback runs off the engine's event loop so a macro with delays never
stalls passthrough of the device's other keys. One Player exists per
grabbed device; a play request while a macro still plays is ignored
(no queueing, so a held or bouncing trigger cannot pile up input).

A macro can repeat: ``play`` takes a number of iterations, or None to loop
until ``stop()``. Iterations are spaced at least MIN_ITERATION_MS apart so a
loop without delays cannot flood the uinput device, and ``current`` names the
playing macro's key so the remapper can stop a loop on a re-press.
"""

import itertools
import logging
import threading
import time
from typing import Any, Callable, Iterable

from hueberry import gui_link
from hueberry.macros import keycodes
from hueberry.macros.model import ACTION_PRESS, ACTION_RELEASE, ACTION_TAP, AppActionStep, DelayStep

logger = logging.getLogger(__name__)

MS_PER_S = 1000
STOP_JOIN_TIMEOUT_S = 1.0
MIN_ITERATION_MS = 10  # minimum time per repeat iteration (throttles delay-less loops)
THREAD_NAME = "macro-player"
PRESS_ACTIONS = (ACTION_PRESS, ACTION_TAP)
RELEASE_ACTIONS = (ACTION_RELEASE, ACTION_TAP)


def start_daemon_thread(target: Callable[[], None]) -> threading.Thread:
    """Run ``target`` on a daemon thread (never blocks engine exit)."""
    thread = threading.Thread(target=target, name=THREAD_NAME, daemon=True)
    thread.start()
    return thread


class Player:
    """Writes macro steps to ``uinput``; ``sleep``, ``start_thread``, ``clock`` and ``notify`` are injectable.

    ``notify`` delivers an app-action step's action name to the GUI (returns success).

    ``lock`` serialises whole reports (event + SYN) against the remapper's
    passthrough writes on the same uinput device.
    """

    def __init__(
        self,
        uinput: Any,
        sleep: Callable[[float], Any] | None = None,
        start_thread: Callable[[Callable[[], None]], Any] = start_daemon_thread,
        clock: Callable[[], float] = time.monotonic,
        *,
        notify: Callable[[str], bool] = gui_link.send_action,
    ) -> None:
        from evdev import ecodes  # lazy: optional dependency

        self._uinput = uinput
        self._ev_key = ecodes.EV_KEY
        self._cancel = threading.Event()
        self._sleep = sleep if sleep is not None else self._cancel.wait  # cancellable delays
        self._start_thread = start_thread
        self._clock = clock
        self._notify = notify
        self._state_lock = threading.Lock()
        self._playing = False
        self._current: Any = None
        self._thread: Any = None
        self.lock = threading.Lock()

    @property
    def playing(self) -> bool:
        """True while a macro is running."""
        with self._state_lock:
            return self._playing

    @property
    def current(self) -> Any:
        """The ``key`` passed to the running ``play()``, or None when idle."""
        with self._state_lock:
            return self._current

    def play(self, steps: Iterable, iterations: int | None = 1, key: Any = None) -> bool:
        """Start playing ``steps`` ``iterations`` times (None: until ``stop()``).

        ``key`` identifies the macro (see ``current``). Returns False (ignored)
        if a macro is already playing.
        """
        with self._state_lock:
            if self._playing:
                logger.info("Macro trigger ignored: a macro is still playing")
                return False
            self._playing = True
            self._current = key
        self._cancel.clear()
        steps = list(steps)
        self._thread = self._start_thread(lambda: self.run(steps, iterations))
        return True

    def run(self, steps: Iterable, iterations: int | None = 1) -> None:
        """Play synchronously, repeating as asked; always releases keys it left pressed."""
        steps = list(steps)
        pressed: set[int] = set()
        rounds = itertools.count() if iterations is None else range(iterations)
        try:
            for index in rounds:
                if self._cancel.is_set():
                    break
                started = self._clock()
                self._iterate(steps, pressed)
                if iterations is None or index + 1 < iterations:
                    self._pace(started)
        except OSError:
            logger.exception("Macro playback failed")
        finally:
            self._release(pressed)
            with self._state_lock:
                self._playing = False
                self._current = None

    def _iterate(self, steps: list, pressed: set[int]) -> None:
        """One pass over ``steps``, checking for cancellation before each step."""
        for step in steps:
            if self._cancel.is_set():
                return
            self._perform(step, pressed)

    def _pace(self, started: float) -> None:
        """Sleep (cancellably) so an iteration takes at least MIN_ITERATION_MS."""
        elapsed_ms = (self._clock() - started) * MS_PER_S
        if elapsed_ms < MIN_ITERATION_MS:
            self._sleep((MIN_ITERATION_MS - elapsed_ms) / MS_PER_S)

    def _perform(self, step: Any, pressed: set[int]) -> None:
        if isinstance(step, DelayStep):
            self._sleep(step.ms / MS_PER_S)
            return
        if isinstance(step, AppActionStep):
            self._notify_app(step.action)
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

    def _notify_app(self, action: str) -> None:
        """Send an app action to the GUI (never under ``lock``); failures only log."""
        try:
            delivered = self._notify(action)
        except Exception:  # noqa: BLE001 - a GUI hiccup must never kill the worker
            logger.exception("App action %s failed", action)
            return
        if not delivered:
            logger.warning("App action %s was not delivered", action)

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
