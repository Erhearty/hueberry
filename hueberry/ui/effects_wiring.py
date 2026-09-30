# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Wire the per-key Effects page into the main window.

Kept out of :mod:`hueberry.ui.main_window` so that file stays small. The
window asks :func:`add_page` for the page, then :func:`connect_window` for
the nav button, the Ctrl+E action and the :class:`KeyEventPoller` that feeds
key presses from the macro engine to the advanced runtime while a shown
effect reacts to them. :func:`restore_last` shows the last activated preset
on the devices no other lighting took, and a :class:`PresetForgetter` forgets it when other lighting takes its last
device.
"""

import logging
from typing import Any, Callable, Iterable

from PyQt6.QtCore import QCoreApplication, QObject, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QStackedWidget, QWidget

from hueberry.backend import advanced_preset_store, advanced_runtime
from hueberry.backend.advanced_presets import AdvancedPreset
from hueberry.backend.animator_targets import device_serial
from hueberry.settings import LAST_ADVANCED_PRESET, Settings
from hueberry.ui import lighting_restore, worker
from hueberry.ui.effects_page import EffectsPage

__all__ = ["EffectsNav", "KeyEventPoller", "PresetForgetter", "add_page", "connect_window",
           "restore_last"]

logger = logging.getLogger(__name__)

EFFECTS_TEXT = "Create effect\u2026"
EFFECTS_SHORTCUT = "Ctrl+E"
EFFECTS_TIP = "Create per-key effects (Ctrl+E)"
POLL_HZ = 30
MS_PER_SECOND = 1000
POLL_INTERVAL_MS = MS_PER_SECOND // POLL_HZ
WATCH_INTERVAL_MS = 1000  # how often to check whether key events are needed
FIRST_CURSOR = 0
EVENTS_KEY = "events"
NEXT_KEY = "next"
NO_NAMES: list[str] = []  # key_watch argument that stops watching


class EffectsNav(QObject):
    """The Effects nav button and action; opens the page and returns to the previous one."""

    def __init__(self, window: Any, page: EffectsPage) -> None:
        super().__init__(window)
        self._window = window
        self.page = page
        self._before: QWidget | None = None
        self.button = window.header.add_nav(EFFECTS_TEXT, EFFECTS_TIP)
        self.action = QAction(EFFECTS_TEXT, window)
        self.action.setShortcut(QKeySequence(EFFECTS_SHORTCUT))
        self.action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        window.addAction(self.action)
        self.action.triggered.connect(self.show_page)
        self.button.clicked.connect(self.show_page)
        page.back_requested.connect(self.leave_page)

    def show_page(self) -> None:
        """Open the Effects page, remembering the page to return to."""
        stack = self._window.stack
        current = stack.currentWidget()
        if current is not self.page:
            self._before = current
        stack.setCurrentWidget(self.page)
        self.page.device_list.setFocus()

    def leave_page(self) -> None:
        """Return to the page shown before Effects, then reload (it may be stale)."""
        window = self._window
        previous = self._before or window.home_page
        self._before = None
        window.stack.setCurrentWidget(previous)
        window.reload()
        if window.stack.currentWidget() is window.home_page:
            window.home_page.focus_selected()


class KeyEventPoller(QObject):
    """Polls the engine's key events at :data:`POLL_HZ` while the runtime needs them.

    A failed request forgets the watch and pauses polling until the next
    :meth:`sync` tick sends ``key_watch`` again; a cursor going backwards
    means the engine restarted. The first reply after a (re)started watch only
    sets the cursor: presses buffered before it are stale.
    """

    def __init__(self, engine: Any, names: Callable[[], dict[str, str]],
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._names = names  # {OpenRazer device name: serial} of the shown devices
        self._watching: dict[str, str] = {}
        self._since = FIRST_CURSOR
        self._in_flight = False
        self._fresh = True  # the next reply only sets the cursor
        self._failing = False  # inside a failure streak (logged once)
        self.timer = QTimer(self)
        self.timer.setInterval(POLL_INTERVAL_MS)
        self.timer.timeout.connect(self.poll)
        self.watch_timer = QTimer(self)
        self.watch_timer.setInterval(WATCH_INTERVAL_MS)
        self.watch_timer.timeout.connect(self.sync)
        if engine is not None:
            self.watch_timer.start()

    def is_polling(self) -> bool:
        """True while key events are being polled."""
        return self.timer.isActive()

    def sync(self) -> None:
        """Start or stop polling to match ``runtime.needs_key_events()``."""
        if self._engine is None:
            return
        try:
            needed = advanced_runtime.shared_runtime().needs_key_events()
            names = self._names() if needed else {}
        except Exception:  # a failing runtime must not break the timer
            logger.exception("Checking for key events failed")
            needed, names = False, {}
        if needed and names != self._watching:
            self._start(names)
        elif not needed and self.timer.isActive():
            self._stop()

    def poll(self) -> None:
        """Fetch new key-downs and feed them to the runtime (one request at a time)."""
        if self._in_flight or self._engine is None:
            return
        self._in_flight = True
        since, names = self._since, dict(self._watching)
        self._run(lambda: self._engine.key_events(since),
                  lambda result: self._on_events(names, result), self._on_events_failed)

    @pyqtSlot()
    def release_watch(self) -> None:
        """Stop polling and, if watching, tell the engine to stop (synchronous, never raises)."""
        self.timer.stop()
        self.watch_timer.stop()
        if self._engine is None or not self._watching:
            return
        self._watching = {}
        try:
            self._engine.key_watch(NO_NAMES)
        except Exception:  # best effort on quit
            logger.warning("Could not stop watching key presses", exc_info=True)

    def _start(self, names: dict[str, str]) -> None:
        self._watching = names
        self._fresh = True
        watched = sorted(names)
        self.timer.start()  # before the request: its failure stops the timer
        self._run(lambda: self._engine.key_watch(watched), None, self._on_watch_failed)
        logger.info("Watching key presses on %s", ", ".join(watched))

    def _stop(self) -> None:
        self.timer.stop()
        self._watching = {}
        self._run(lambda: self._engine.key_watch(NO_NAMES), None, self._on_watch_failed)
        logger.info("Stopped watching key presses")

    def _on_events(self, names: dict[str, str], result: Any) -> None:
        self._in_flight = False
        try:
            cursor = int(result.get(NEXT_KEY, self._since))
            events = result.get(EVENTS_KEY, [])
            self._failing = False
            if self._fresh or cursor < self._since:
                self._adopt(cursor)
                return
            self._since = cursor
            advanced_runtime.shared_runtime().feed_presses(names, events)
        except Exception:  # malformed replies are logged, never raised
            logger.warning("Could not use key events %r", result, exc_info=True)

    def _adopt(self, cursor: int) -> None:
        """Take ``cursor`` without feeding; a cursor going backwards means a restart."""
        if not self._fresh:
            logger.info("Key events restarted; watching again")
            self._lose_watch()
        self._fresh = False
        self._since = cursor

    def _on_watch_failed(self, message: str) -> None:
        self._lose_watch()
        self._log_failure(message)

    def _on_events_failed(self, message: str) -> None:
        self._in_flight = False
        self._lose_watch()
        self._log_failure(message)

    def _lose_watch(self) -> None:
        """Forget the watch and pause polling; the next sync tick sends key_watch again."""
        self._watching = {}
        self.timer.stop()

    def _log_failure(self, message: str) -> None:
        """Log the first failure of a streak only."""
        if not self._failing:
            logger.warning("Key events: %s", message)
        self._failing = True

    def _run(self, fn: Callable[[], Any], on_done: Callable[[Any], None] | None,
             on_error: Callable[[str], None]) -> None:
        try:
            worker.run_async(fn, on_done, on_error)
        except Exception as exc:  # never let an exception escape a timer slot
            logger.exception("Could not start a key events job")
            on_error(str(exc))


def add_page(stack: QStackedWidget) -> EffectsPage:
    """Create the Effects page and add it to ``stack``."""
    page = EffectsPage(parent=stack)
    stack.addWidget(page)
    return page


def connect_window(window: Any, engine: Any) -> EffectsNav:
    """Add the nav button/shortcut for ``window.effects_page``, start the key poller.

    Also stops the key watch on quit, forgets the last preset when other
    lighting takes its last device (:class:`PresetForgetter`) and keeps the
    lighting panel's running label current (also after :func:`restore_last`).
    """
    page = window.effects_page
    nav = EffectsNav(window, page)
    page.status.connect(window.show_status)
    names = page.device_names
    nav.poller = KeyEventPoller(engine, lambda: _active_names(names()), window)
    app = QCoreApplication.instance()
    if app is not None:  # before the engine's own quit handler stops it
        app.aboutToQuit.connect(nav.poller.release_watch)
    nav.forgetter = PresetForgetter(window)
    try:
        advanced_runtime.shared_runtime().add_emptied_listener(nav.forgetter.on_emptied)
    except Exception:  # the window still works without it
        logger.exception("Could not watch the per-key preset")
    nav.running_relay = lighting_restore.connect_panel(window.lighting_panel)
    return nav


class PresetForgetter(QObject):
    """Forgets the last per-key preset when other lighting takes its last device.

    :meth:`on_emptied` is the runtime's emptied listener (it fires only when
    a claim released the last device, never on a disconnect) and may run on
    any thread; the settings are changed on this object's (the GUI) thread,
    and only while they still name the emptied preset.
    """

    emptied = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None, settings: Settings | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self.emptied.connect(self._forget)

    def on_emptied(self, key: str) -> None:
        """Runtime emptied listener: hand ``key`` to the GUI thread."""
        try:
            self.emptied.emit(str(key))
        except RuntimeError:  # the window is gone
            return

    @pyqtSlot(str)
    def _forget(self, key: str) -> None:
        try:
            settings = self._settings if self._settings is not None else Settings()
            if key and settings.last_advanced_preset == key:
                settings.set(LAST_ADVANCED_PRESET, "")
                logger.info("Forgot per-key preset %s: its devices show other lighting", key)
        except Exception:  # never raised into Qt
            logger.exception("Forgetting the per-key preset failed")


def _programmed(preset: AdvancedPreset) -> set[str]:
    """Serials ``preset`` has a program for."""
    return {program.serial for program in preset.programs}


def _active_names(serial_names: dict[str, str]) -> dict[str, str]:
    """{name: serial} of the devices the runtime shows."""
    active = set(advanced_runtime.shared_runtime().active_serials())
    return {name: serial for serial, name in serial_names.items() if serial in active}


def restore_last(devices: Iterable[Any], settings: Settings | None = None) -> None:
    """Show the last activated per-key preset unless it is active already.

    Only devices no other lighting took (``runtime.claimed_away()``) are used, so a reload never takes back
    a device the user gave other lighting, while a reconnect after a daemon
    disconnect shows the preset again. A preset that no longer exists is
    forgotten. Errors are logged, never raised.
    """
    devices = list(devices)
    try:
        settings = settings if settings is not None else Settings()
        key = settings.last_advanced_preset
        runtime = advanced_runtime.shared_runtime()
        if not key:
            return
        if runtime.active_key() == key:
            runtime.refresh(devices)
            return
        presets, error = advanced_preset_store.load()
        preset = advanced_preset_store.find_preset(key, presets)
        if preset is None:
            if error is None:
                settings.set(LAST_ADVANCED_PRESET, "")
            return
        wanted = _programmed(preset)
        taken = runtime.claimed_away()
        free = [dev for dev in devices
                if device_serial(dev) in wanted and device_serial(dev) not in taken]
        if free:
            runtime.activate(preset, free, reclaim=False)
    except Exception:  # restoring must never break a reload
        logger.exception("Restoring the per-key preset failed")
