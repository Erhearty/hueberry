# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Background animator for lighting presets (:mod:`hueberry.backend.effects`).

A *run* is one preset shown on one device on its own, or on a synced group of
devices laid side by side on one grid (:mod:`hueberry.backend.led_layout`).
Every run is animated from one daemon thread; a new run of a preset that is
already running adopts that run's phase, so devices showing the same preset
stay in sync. Runs are guarded by a short-held lock; frames are rendered
(D-Bus calls) outside it, under a separate render lock, so callers on the UI
thread never wait for a slow device in :meth:`Animator.start`,
:meth:`Animator.is_running` or :meth:`Animator.refresh`. The thread starts
lazily on the first :meth:`Animator.start` and retires when nothing is left to
animate. Nothing here imports openrazer or Qt: device objects are passed in
by the caller, and nothing here touches saved state (see
:mod:`hueberry.backend.lighting_state`).
"""

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Iterable

from hueberry.backend import effects, presets
from hueberry.backend.animator_targets import (
    Target, build_target, device_serial, render_safely, supports,
)
from hueberry.backend.animator_targets import restore as restore_target
from hueberry.backend.effects import Preset
from hueberry.backend.led_layout import Layout, group_layout

__all__ = ["Animator", "RunInfo", "build_target", "device_serial", "shared_animator",
           "supports"]

logger = logging.getLogger(__name__)

THREAD_NAME = "hueberry-presets"
JOIN_TIMEOUT_S = 1.0  # longest wait for the animation thread on shutdown
START_PHASE = 0.0


@dataclass(frozen=True)
class RunInfo:
    """A snapshot of one run: its preset, devices (in grid order) and mode."""

    preset: Preset
    serials: tuple[str, ...]
    grouped: bool


@dataclass
class _Run:
    """One preset shown on one device or a synced group, with its own phase."""

    preset: Preset
    targets: list[Target]
    grouped: bool
    phase: float = START_PHASE
    layout: Layout = field(init=False)

    def __post_init__(self) -> None:
        self.relayout()

    def relayout(self) -> None:
        """Recompute the grid after the members changed."""
        self.layout = group_layout(target.shape() for target in self.targets)

    def info(self) -> RunInfo:
        """Immutable snapshot for callers outside the animator."""
        serials = tuple(target.serial for target in self.targets)
        return RunInfo(self.preset, serials, self.grouped)


def _unique_targets(devices: Iterable[Any]) -> list[Target]:
    """Targets of the supported ``devices``, first occurrence of each serial only."""
    targets: dict[str, Target] = {}
    for dev in devices:
        target = build_target(dev) if dev is not None else None
        if target is not None and target.serial not in targets:
            targets[target.serial] = target
    return list(targets.values())


def _render_run(preset: Preset, targets: list[Target], layout: Layout, phase: float) -> None:
    """Paint one frame of ``preset`` on the run's active, unpaused targets.

    A non-animated preset paints each target once per (preset, layout): a
    target repaints when what it last painted differs, so a frame of an older
    preset that was still in flight never hides the current one.
    """
    animated = effects.is_animated(preset)
    frames = effects.render_run(preset, layout, phase)
    for target in targets:
        fresh = animated or not target.painted_with(preset, layout)
        if target.active and not target.paused and fresh:
            render_safely(target, frames[target.serial], preset, layout)


class Animator:
    """Animate lighting presets on single devices and synced groups.

    :param fps: frames per second of the animation thread.
    :param start_thread: False keeps it passive; call :meth:`step` directly.
    """

    def __init__(self, fps: int = presets.FPS, start_thread: bool = True) -> None:
        self._fps = fps
        self._interval = 1 / fps
        self._start_thread = start_thread
        self._lock = threading.RLock()  # guards _runs only; held briefly
        self._render_lock = threading.Lock()  # serializes frame rendering and restores
        self._runs: list[_Run] = []
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, dev: Any, preset: Preset = presets.ERHEART) -> bool:
        """Show ``preset`` on ``dev`` alone (leaving any other run); False if unsupported."""
        target = build_target(dev) if dev is not None else None
        if target is None:
            logger.info("Preset %s not supported on this device", preset.key)
            return False
        self._add_run([target], preset, grouped=False)
        logger.info("Preset %s started on %s (%s)", preset.key, target.serial, target.kind)
        return True

    def start_group(self, devices: Iterable[Any], preset: Preset) -> list[str]:
        """Show ``preset`` on ``devices`` as one synced group, in the given order.

        Each device leaves any run it was in. Unsupported devices are skipped.
        Returns the serials actually started, in grid order ([] when none).
        """
        targets = _unique_targets(devices)
        if not targets:
            logger.info("Preset %s not supported on any grouped device", preset.key)
            return []
        self._add_run(targets, preset, grouped=True)
        logger.info("Preset %s started on a group of %d devices", preset.key, len(targets))
        return [target.serial for target in targets]

    def update_preset(self, preset: Preset) -> int:
        """Show the edited ``preset`` on every run of its key, keeping each run's phase.

        Returns the number of runs updated; their devices repaint on the next step.
        """
        with self._lock:
            updated = [run for run in self._runs if run.preset.key == preset.key]
            for run in updated:
                run.preset = preset  # targets repaint: they last painted another preset
        logger.info("Preset %s updated on %d runs", preset.key, len(updated))
        return len(updated)

    def running_preset(self, serial: str) -> str | None:
        """Key of the preset shown on ``serial``, or None when it is not animated."""
        with self._lock:
            found = self._find(serial)
            return found[0].preset.key if found is not None else None

    def stop(self, serial: str, restore: bool = True) -> bool:
        """Stop animating ``serial``; ``restore`` asks a matrix for its last effect.

        Only this device leaves its run: other members of a group keep running
        on a new layout without it.

        Waits for any in-flight frame to finish first, so no frame lands after
        a following effect write. It may therefore block for one frame (a slow
        D-Bus call) plus the restore: call it off the UI thread.
        """
        with self._lock:
            target = self._detach(serial)
        if target is None:
            return False
        with self._render_lock:
            if restore:
                restore_target(target)
        logger.info("Preset animation stopped on %s", serial)
        return True

    def is_running(self, serial: str | None = None) -> bool:
        """True when ``serial`` (or, if None, any device) is being animated."""
        with self._lock:
            if serial is None:
                return bool(self._runs)
            return self._find(serial) is not None

    def runs(self) -> list[RunInfo]:
        """Snapshots of every run."""
        with self._lock:
            return [run.info() for run in self._runs]

    def step(self) -> None:
        """Render one frame of every run and advance each run's phase.

        The runs are snapshotted under ``_lock`` and rendered outside it, so
        a blocking device never holds up :meth:`start` / :meth:`is_running`.
        """
        with self._render_lock:
            with self._lock:
                snapshot = [(run.preset, list(run.targets), run.layout, run.phase)
                            for run in self._runs]
                for run in self._runs:
                    run.phase = effects.advance_phase(run.preset, run.phase, self._fps)
            for preset, targets, layout, phase in snapshot:
                _render_run(preset, targets, layout, phase)

    def refresh(self, devices: Iterable[Any]) -> None:
        """Rebind targets to the current device objects; drop devices that are gone."""
        present = {}
        for dev in devices:
            serial = device_serial(dev)
            if serial is not None:
                present[serial] = dev
        with self._lock:
            serials = [target.serial for run in self._runs for target in run.targets]
        # build_target does D-Bus reads: keep it outside the lock.
        rebuilt = {s: build_target(present[s]) if s in present else None for s in serials}
        with self._lock:
            for serial, target in rebuilt.items():
                self._rebind(serial, target)

    def shutdown(self, timeout: float = JOIN_TIMEOUT_S) -> None:
        """Stop the thread and every animation (restoring matrix effects)."""
        with self._lock:
            self._stop_event.set()
            thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        with self._lock:
            serials = [target.serial for run in self._runs for target in run.targets]
        for serial in serials:
            self.stop(serial)

    # -- runs (caller holds the lock) --------------------------------------------

    def _find(self, serial: str) -> tuple[_Run, int] | None:
        """The run showing ``serial`` and its index in that run."""
        for run in self._runs:
            for index, target in enumerate(run.targets):
                if target.serial == serial:
                    return run, index
        return None

    def _detach(self, serial: str) -> Target | None:
        """Take ``serial`` out of its run; an emptied run is removed."""
        found = self._find(serial)
        if found is None:
            return None
        run, index = found
        target = run.targets.pop(index)
        target.active = False
        if run.targets:
            run.relayout()  # members repaint: they last painted the old layout
        else:
            self._runs.remove(run)
        return target

    def _add_run(self, targets: list[Target], preset: Preset, grouped: bool) -> None:
        """Replace any animation of the targets with one new run of ``preset``."""
        with self._lock:
            phase = next((run.phase for run in self._runs if run.preset.key == preset.key),
                         START_PHASE)
            for target in targets:
                self._detach(target.serial)
            self._runs.append(_Run(preset, targets, grouped, phase))
            self._ensure_thread()

    def _rebind(self, serial: str, target: Target | None) -> None:
        """Swap in a rebuilt target, or drop ``serial`` from its run."""
        found = self._find(serial)
        if found is None:
            return  # stopped while rebuilding
        if target is None:
            self._detach(serial)
            logger.info("Device %s gone, dropping its animation", serial)
            return
        run, index = found
        run.targets[index].active = False
        run.targets[index] = target
        run.relayout()

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
            if self._runs:
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
