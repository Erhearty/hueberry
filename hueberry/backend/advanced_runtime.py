# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Background runtime showing one advanced (per-key) preset on keyboard matrices.

At most one :class:`AdvancedPreset` is active. :meth:`AdvancedRuntime.activate`
paints full ``rows x cols`` frames through ``fx.advanced`` from a lazy daemon
thread; keys outside every group are black. Devices claimed for other
lighting (:mod:`hueberry.backend.lighting_state`) are released. Key presses fed
by :meth:`AdvancedRuntime.feed_presses` drive the reactive and ripple effects.

State is guarded by a short lock and frames are rendered (D-Bus calls) under a
separate render lock.
Blocking methods (activate, stop, release, shutdown) belong off the UI
thread. Nothing here imports openrazer or Qt.
"""

import logging
import random
import threading
import time
from typing import Any, Callable, Iterable, Mapping, Sequence

from hueberry.backend import lighting_state
from hueberry.backend.advanced_frames import animated as _animated
from hueberry.backend.advanced_frames import frame as _frame
from hueberry.backend.advanced_frames import press_cell as _press_cell
from hueberry.backend.advanced_frames import preset_press_lifetime as _press_lifetime
from hueberry.backend.advanced_presets import AdvancedPreset
from hueberry.backend.animator_targets import (
    FPS, KIND_MATRIX, Target, build_target, device_serial, render_safely,
)
from hueberry.backend.animator_targets import restore as restore_target
from hueberry.backend.effects import PresetError
from hueberry.backend.key_effect_render import Press
from hueberry.backend.key_effects import uses_presses

__all__ = ["AdvancedRuntime", "shared_runtime"]

logger = logging.getLogger(__name__)

THREAD_NAME = "hueberry-advanced"
JOIN_TIMEOUT_S = 1.0  # longest wait for the render thread on shutdown
EVENT_CODE = 0  # a key event is [code, seq, t_ms]

State = tuple[str | None, frozenset[str]]  # (active preset key, shown serials)


class AdvancedRuntime:
    """Render one advanced preset on its devices' key matrices.

    :param fps: frames per second of the render thread.
    :param start_thread: False keeps it passive; call :meth:`step` directly.
    :param clock: monotonic seconds (injectable for tests).
    :param rng: random source of the starlight effect.
    """

    def __init__(self, fps: int = FPS, start_thread: bool = True,
                 clock: Callable[[], float] = time.monotonic,
                 rng: random.Random | None = None) -> None:
        self._interval = 1 / fps
        self._start_thread = start_thread
        self._clock = clock
        self._rng = rng if rng is not None else random.Random()
        self._lock = threading.RLock()  # guards the fields below; held briefly
        self._render_lock = threading.Lock()  # serializes frames and restores
        self._preset: AdvancedPreset | None = None
        self._targets: dict[str, Target] = {}
        self._presses: dict[str, list[Press]] = {}
        self._started = 0.0
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._claimed_away: set[str] = set()  # released targets a restore must not re-take
        self._emptied_listeners: list[Callable[[str], None]] = []
        self._change_listeners: list[Callable[[], None]] = []

    # -- control -----------------------------------------------------------------

    def activate(self, preset: AdvancedPreset, devices: Iterable[Any], *,
                 reclaim: bool = True) -> list[str]:
        """Show ``preset`` on its present matrix devices; the serials started.

        Replaces any active preset (devices it no longer uses are restored).
        ``reclaim`` (an explicit activation) forgets :meth:`claimed_away`;
        an automatic restore passes False to keep it.
        """
        if reclaim:
            with self._lock:
                self._claimed_away.clear()
        present = {device_serial(dev): dev for dev in devices}
        wanted = [p.serial for p in preset.programs if p.serial in present]
        built = (build_target(present[serial]) for serial in wanted)
        targets = {t.serial: t for t in built if t is not None and t.kind == KIND_MATRIX}
        with self._lock:
            old = [t for s, t in self._targets.items() if s not in targets]
            self._deactivate(self._targets.values())
            self._preset, self._targets, self._presses = preset, targets, {}
            self._started = self._clock()
            if targets:
                self._ensure_thread()
            else:
                self._preset = None
        self._restore(old)
        logger.info("Advanced preset %s active on %d devices", preset.key, len(targets))
        self._notify_changed()
        return list(targets)

    def update(self, preset: AdvancedPreset) -> bool:
        """Swap in the edited ``preset`` if it is the active one (keeps the clock).

        An invalid ``preset`` is logged and ignored: the previous one stays.
        """
        try:
            preset.validate()
        except PresetError as exc:
            logger.warning("Not showing invalid advanced preset %s: %s", preset.key, exc)
            return False
        with self._lock:
            if self._preset is None or self._preset.key != preset.key:
                return False
            self._preset = preset  # targets repaint: they last painted another object
        self._notify_changed()
        return True

    def stop(self) -> None:
        """Stop the active preset and restore every device's hardware effect."""
        with self._lock:
            before = self._state()
            targets = list(self._targets.values())
            self._deactivate(targets)
            self._preset, self._targets, self._presses = None, {}, {}
            self._claimed_away.clear()
            changed = before != self._state()
        self._restore(targets)
        if targets:
            logger.info("Advanced preset stopped")
        if changed:
            self._notify_changed()

    def release(self, serials: Iterable[str]) -> None:
        """Give ``serials`` back (restored); the other devices keep the preset.

        Released serials are remembered in :meth:`claimed_away`. Emptying an
        active preset tells the :meth:`add_emptied_listener` listeners.
        """
        emptied: str | None = None
        with self._lock:
            before = self._state()
            dropped = [self._targets.pop(s) for s in set(serials) if s in self._targets]
            self._deactivate(dropped)
            for target in dropped:
                self._presses.pop(target.serial, None)
                self._claimed_away.add(target.serial)
            if dropped and not self._targets and self._preset is not None:
                emptied = self._preset.key
            if not self._targets:
                self._preset = None
            listeners = list(self._emptied_listeners)
            changed = before != self._state()
        self._restore(dropped)
        for target in dropped:
            logger.info("Advanced preset released %s", target.serial)
        if emptied is not None:
            self._notify_emptied(listeners, emptied)
        if changed:
            self._notify_changed()

    def add_emptied_listener(self, listener: Callable[[str], None]) -> None:
        """Call ``listener(key)`` when :meth:`release` empties the active preset.

        It runs on the releasing thread, outside the locks; errors are logged.
        Devices dropped by :meth:`refresh` (disconnects) do not count.
        """
        with self._lock:
            self._emptied_listeners.append(listener)

    def add_change_listener(self, listener: Callable[[], None]) -> None:
        """Call ``listener()`` when activate, update, stop, release or refresh changed the state.

        It runs on the calling thread, outside the locks; errors are logged.
        """
        with self._lock:
            self._change_listeners.append(listener)

    def refresh(self, devices: Iterable[Any]) -> None:
        """Rebind targets to the current device objects; drop devices that are gone."""
        present = {device_serial(dev): dev for dev in devices}
        with self._lock:
            before = self._state()
            serials = list(self._targets)
        rebuilt = {s: build_target(present[s]) if s in present else None for s in serials}
        with self._lock:
            for serial, target in rebuilt.items():
                self._rebind(serial, target)
            if not self._targets:
                self._preset = None
            changed = before != self._state()
        if changed:
            self._notify_changed()

    def shutdown(self, timeout: float = JOIN_TIMEOUT_S) -> None:
        """Stop the thread and the active preset (restoring the devices)."""
        with self._lock:
            self._stop_event.set()
            thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        self.stop()

    # -- queries -----------------------------------------------------------------

    def active_key(self) -> str | None:
        """Key of the active preset, or None."""
        with self._lock:
            return self._preset.key if self._preset is not None else None

    def claimed_away(self) -> frozenset[str]:
        """Serials other lighting took since the last explicit activation or stop."""
        with self._lock:
            return frozenset(self._claimed_away)

    def active_serials(self) -> list[str]:
        """Serials the active preset is shown on."""
        with self._lock:
            return list(self._targets)

    def needs_key_events(self) -> bool:
        """True when a shown group reacts to key presses."""
        with self._lock:
            if self._preset is None:
                return False
            return any(uses_presses(group.effect.effect) for program in self._preset.programs
                       if program.serial in self._targets for group in program.groups)

    # -- presses -----------------------------------------------------------------

    def feed_presses(self, serial_for_name: Mapping[str, str],
                     events: Iterable[Sequence[Any]]) -> None:
        """Record key-down ``events`` (``[code, seq, t_ms]``) on the watched devices.

        Events do not say which keyboard they came from, so each one is fed to
        every active device among ``serial_for_name.values()``.
        """
        codes = [int(event[EVENT_CODE]) for event in events]
        if not codes:
            return
        with self._lock:
            now = self._clock() - self._started
            for serial in set(serial_for_name.values()):
                target = self._targets.get(serial)
                if target is None:
                    continue
                presses = self._presses.setdefault(serial, [])
                for code in codes:
                    use, cell = _press_cell(code, target)
                    if use:
                        presses.append((now, cell))

    # -- rendering ---------------------------------------------------------------

    def step(self) -> None:
        """Render one frame on every device (a static-only preset paints once)."""
        with self._render_lock:
            with self._lock:
                preset = self._preset
                if preset is None:
                    return
                t = self._clock() - self._started
                self._prune(t, _press_lifetime(preset))
                snapshot = [(target, list(self._presses.get(serial, ())))
                            for serial, target in self._targets.items()]
            animated = _animated(preset)
            for target, presses in snapshot:
                self._paint(preset, target, t, presses, animated)

    def _paint(self, preset: AdvancedPreset, target: Target, t: float,
               presses: list[Press], animated: bool) -> None:
        """Paint one target unless it is paused, stopped, or already shows a static frame."""
        if not target.active or target.paused:
            return
        if not animated and target.painted is not None and target.painted[0] is preset:
            return
        frame = _frame(preset.program_for(target.serial), target, t, presses, self._rng)
        render_safely(target, frame, preset, None)  # type: ignore[arg-type]

    def _prune(self, t: float, lifetime: float) -> None:
        """Forget presses older than ``lifetime`` (caller holds the lock)."""
        for serial, presses in self._presses.items():
            self._presses[serial] = [p for p in presses if t - p[0] <= lifetime]

    # -- internals ---------------------------------------------------------------

    def _state(self) -> State:
        """The active key and shown serials (caller holds the lock)."""
        return (self._preset.key if self._preset is not None else None,
                frozenset(self._targets))

    def _notify_changed(self) -> None:
        """Call each change listener (outside the locks); failures are logged."""
        with self._lock:
            listeners = list(self._change_listeners)
        for listener in listeners:
            try:
                listener()
            except Exception:  # a listener must not break the runtime
                logger.exception("Advanced preset change listener failed")

    @staticmethod
    def _notify_emptied(listeners: Iterable[Callable[[str], None]], key: str) -> None:
        """Call each emptied listener with ``key``; one failing does not stop the rest."""
        for listener in listeners:
            try:
                listener(key)
            except Exception:  # a listener must not break a claim
                logger.exception("Advanced preset emptied listener failed")

    @staticmethod
    def _deactivate(targets: Iterable[Target]) -> None:
        for target in targets:
            target.active = False

    def _restore(self, targets: Iterable[Target]) -> None:
        """Restore hardware effects after any in-flight frame."""
        targets = list(targets)
        if not targets:
            return
        with self._render_lock:
            for target in targets:
                restore_target(target)

    def _rebind(self, serial: str, target: Target | None) -> None:
        """Swap in a rebuilt target, or drop a gone device (caller holds the lock)."""
        old = self._targets.get(serial)
        if old is None:
            return
        old.active = False
        if target is None or target.kind != KIND_MATRIX:
            del self._targets[serial]
            self._presses.pop(serial, None)
            logger.info("Device %s gone, dropping its advanced preset", serial)
            return
        self._targets[serial] = target

    def _ensure_thread(self) -> None:
        """Start the render thread if needed (caller holds the lock)."""
        if not self._start_thread or self._thread is not None:
            return
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(self._stop_event,),
                                        name=THREAD_NAME, daemon=True)
        self._thread.start()

    def _run(self, stop_event: threading.Event) -> None:
        while not stop_event.wait(self._interval):
            self.step()
            if self._retire_if_idle():
                return

    def _retire_if_idle(self) -> bool:
        with self._lock:
            if self._preset is not None:
                return False
            if self._thread is threading.current_thread():
                self._thread = None
            return True


_shared: AdvancedRuntime | None = None
_shared_lock = threading.Lock()


def shared_runtime() -> AdvancedRuntime:
    """The process-wide runtime, created on first use.

    It lets go of any device the shared lighting state claims for a preset
    or an effect (:meth:`LightingState.claim`).
    """
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = AdvancedRuntime()
            lighting_state.shared_lighting_state().add_claim_listener(_shared.release)
        return _shared
