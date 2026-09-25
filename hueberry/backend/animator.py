# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Background animator for the Erheart preset (:mod:`hueberry.backend.presets`).

Devices are animated from one daemon thread so every device shares the same
wave offset (they stay in sync). Targets are keyed by device serial and
guarded by a short-held lock; frames are rendered (D-Bus calls) outside it,
under a separate render lock, so callers on the UI thread never wait for a
slow device in :meth:`Animator.start`, :meth:`Animator.is_running` or
:meth:`Animator.refresh`. The thread starts lazily on the first :meth:`Animator.start`
and retires when nothing is left to animate. Nothing here imports openrazer or
Qt: device objects are passed in by the caller.
"""

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Iterable

from hueberry.backend import presets
from hueberry.backend.devices import MATRIX_CAPABILITY, list_zones
from hueberry.backend.lighting import is_effect_supported

logger = logging.getLogger(__name__)

STATIC_EFFECT = "static"
THREAD_NAME = "hueberry-erheart"
JOIN_TIMEOUT_S = 1.0  # longest wait for the animation thread on shutdown
KIND_MATRIX = "matrix"  # per-key wave through fx.advanced
KIND_ZONES = "zones"  # one animated colour through zone.static
KIND_FIXED = "fixed"  # a serial override: one static colour, applied once


@dataclass
class _Target:
    """One animated device and how to paint it."""

    serial: str
    kind: str
    advanced: Any = None
    rows: int = 0
    cols: int = 0
    zones: list = field(default_factory=list)
    colour: tuple[int, int, int] | None = None
    applied: bool = False
    paused: bool = False  # stale device object; resumes on refresh()
    active: bool = True  # False once stopped or replaced; never rendered again
    warned: bool = False  # one warning per target for unexpected errors


def device_serial(dev: Any) -> str | None:
    """The device's serial, or None when it cannot be read."""
    try:
        return str(dev.serial)
    except Exception:  # D-Bus errors
        logger.warning("Could not read device serial", exc_info=True)
        return None


def _static_zones(dev: Any) -> list:
    return [zone.obj for zone in list_zones(dev) if is_effect_supported(dev, zone, STATIC_EFFECT)]


def _matrix_target(serial: str, dev: Any) -> _Target | None:
    try:
        advanced = dev.fx.advanced if dev.has(MATRIX_CAPABILITY) else None
        if advanced is None:
            return None
        return _Target(serial, KIND_MATRIX, advanced=advanced,
                       rows=int(advanced.rows), cols=int(advanced.cols))
    except Exception:  # D-Bus errors / no advanced matrix
        logger.warning("No usable key matrix on %s", serial, exc_info=True)
        return None


def build_target(dev: Any) -> _Target | None:
    """Describe how to animate ``dev``, or None when it cannot show the preset."""
    serial = device_serial(dev)
    if serial is None:
        return None
    if serial in presets.SERIAL_OVERRIDES:
        zones = _static_zones(dev)
        colour = presets.SERIAL_OVERRIDES[serial]
        return _Target(serial, KIND_FIXED, zones=zones, colour=colour) if zones else None
    target = _matrix_target(serial, dev)
    if target is not None:
        return target
    zones = _static_zones(dev)
    return _Target(serial, KIND_ZONES, zones=zones) if zones else None


def supports(dev: Any) -> bool:
    """True when the Erheart preset can be shown on ``dev``."""
    return dev is not None and build_target(dev) is not None


def _paint(zones: list, colour: tuple[int, int, int]) -> None:
    for zone in zones:
        zone.static(*colour)


def _draw_matrix(target: _Target, offset: float) -> None:
    matrix = target.advanced.matrix
    for row in range(target.rows):
        for col in range(target.cols):
            matrix[row, col] = presets.matrix_colour(row, col, target.rows, target.cols, offset)
    target.advanced.draw()


def _render(target: _Target, offset: float) -> None:
    if target.kind == KIND_MATRIX:
        _draw_matrix(target, offset)
    elif target.kind == KIND_ZONES:
        _paint(target.zones, presets.zone_colour(offset))
    elif not target.applied:
        _paint(target.zones, target.colour)
        target.applied = True


def _render_safely(target: _Target, offset: float) -> None:
    """Render one frame; pause the target on stale errors, keep it otherwise."""
    try:
        _render(target, offset)
    except Exception as exc:  # D-Bus / sysfs errors from the device
        if presets.is_not_ready_error(exc):
            logger.debug("Device %s not ready, retrying: %s", target.serial, exc)
        elif presets.is_stale_error(exc):
            logger.info("Device %s is stale, pausing until reload", target.serial)
            target.paused = True
        elif not target.warned:
            logger.warning("Animating %s failed", target.serial, exc_info=True)
            target.warned = True


def _restore(target: _Target) -> None:
    if target.kind != KIND_MATRIX:
        return
    try:
        target.advanced.restore()
    except Exception:  # D-Bus errors; the device may be gone
        logger.warning("Could not restore lighting of %s", target.serial, exc_info=True)


class Animator:
    """Animate the Erheart preset on several devices in sync.

    :param fps: frames per second of the animation thread.
    :param start_thread: False keeps it passive; call :meth:`step` directly.
    """

    def __init__(self, fps: int = presets.FPS, start_thread: bool = True) -> None:
        self._fps = fps
        self._interval = 1 / fps
        self._start_thread = start_thread
        self._lock = threading.RLock()  # guards _targets and _offset only; held briefly
        self._render_lock = threading.Lock()  # serializes frame rendering and restores
        self._targets: dict[str, _Target] = {}
        self._offset = 0.0
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, dev: Any) -> bool:
        """Animate ``dev`` (replacing any animation of its serial); False if unsupported."""
        target = build_target(dev)
        if target is None:
            logger.info("Erheart preset not supported on this device")
            return False
        with self._lock:
            old = self._targets.get(target.serial)
            if old is not None:
                old.active = False
            self._targets[target.serial] = target
            self._ensure_thread()
        logger.info("Erheart animation started on %s (%s)", target.serial, target.kind)
        return True

    def stop(self, serial: str, restore: bool = True) -> bool:
        """Stop animating ``serial``; ``restore`` asks a matrix for its last effect.

        Waits for any in-flight frame to finish first, so no frame lands after
        a following effect write. It may therefore block for one frame (a slow
        D-Bus call) plus the restore: call it off the UI thread.
        """
        with self._lock:
            target = self._targets.pop(serial, None)
            if target is None:
                return False
            target.active = False
        with self._render_lock:
            if restore:
                _restore(target)
        logger.info("Erheart animation stopped on %s", serial)
        return True

    def is_running(self, serial: str | None = None) -> bool:
        """True when ``serial`` (or, if None, any device) is being animated."""
        with self._lock:
            return bool(self._targets) if serial is None else serial in self._targets

    def step(self) -> None:
        """Render one frame on every active target and advance the shared offset.

        The targets are snapshotted under ``_lock`` and rendered outside it, so
        a blocking device never holds up :meth:`start` / :meth:`is_running`.
        """
        with self._render_lock:
            with self._lock:
                targets = list(self._targets.values())
                offset = self._offset
                self._offset = presets.next_offset(offset)
            for target in targets:
                if target.active and not target.paused:
                    _render_safely(target, offset)

    def refresh(self, devices: Iterable[Any]) -> None:
        """Rebind targets to the current device objects; drop devices that are gone."""
        present = {}
        for dev in devices:
            serial = device_serial(dev)
            if serial is not None:
                present[serial] = dev
        with self._lock:
            serials = list(self._targets)
        # build_target does D-Bus reads: keep it outside the lock.
        rebuilt = {s: build_target(present[s]) if s in present else None for s in serials}
        with self._lock:
            for serial, target in rebuilt.items():
                self._rebind(serial, target)

    def _rebind(self, serial: str, target: _Target | None) -> None:
        """Swap in a rebuilt target, or drop ``serial`` (caller holds the lock)."""
        old = self._targets.pop(serial, None)
        if old is None:
            return  # stopped while rebuilding
        old.active = False
        if target is None:
            logger.info("Device %s gone, dropping its animation", serial)
        else:
            self._targets[serial] = target

    def shutdown(self, timeout: float = JOIN_TIMEOUT_S) -> None:
        """Stop the thread and every animation (restoring matrix effects)."""
        with self._lock:
            self._stop_event.set()
            thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        with self._lock:
            serials = list(self._targets)
        for serial in serials:
            self.stop(serial)

    # -- thread ----------------------------------------------------------------

    def _ensure_thread(self) -> None:
        """Start the animation thread if needed (caller holds the lock)."""
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
            if self._targets:
                return False
            if self._thread is threading.current_thread():
                self._thread = None
            return True


_shared: Animator | None = None
_shared_lock = threading.Lock()


def shared_animator() -> Animator:
    """The process-wide :class:`Animator`, created on first use."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = Animator()
        return _shared
