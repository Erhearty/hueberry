# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Turn every Razer LED off when Hueberry quits, logs out or the system powers off.

:class:`ShutdownLighting` stops the per-key runtime without restoring the
devices, then switches every lighting zone off. It runs once, from Qt's
``aboutToQuit`` (which also fires on logout and poweroff) or a SIGTERM /
SIGHUP / SIGINT, which are routed into the event loop through
``signal.set_wakeup_fd`` and a :class:`QSocketNotifier` so the app quits
normally (and ``aboutToQuit`` fires). The session manager's
``commitDataRequest`` is deliberately not used: a logout can still be cancelled
after it fires, and it also fires for plain session saves.
"""

import logging
import signal
import socket
from typing import Any, Callable

from PyQt6.QtCore import QCoreApplication, QSocketNotifier

from hueberry.backend import advanced_runtime, lights_off

__all__ = ["QUIT_SIGNALS", "ShutdownLighting"]

logger = logging.getLogger(__name__)

QUIT_SIGNALS = (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)
DRAIN_BYTES = 64  # bytes read per recv while draining the wakeup socket


def _ignore_signal(signum: int, frame: Any) -> None:
    """Python-level handler: the wakeup fd already told the event loop."""


class ShutdownLighting:
    """Switch the LEDs of ``service``'s devices off once, on any shutdown path.

    :param service: the :class:`~hueberry.backend.daemon.DaemonService`.
    :param runtime_getter: returns the per-key runtime (default: the shared one).
    """

    def __init__(self, service: Any,
                 runtime_getter: Callable[[], Any] | None = None) -> None:
        self._service = service
        self._runtime_getter = runtime_getter
        self._ran = False
        self._app: Any = None
        self._previous_handlers: dict[int, Any] = {}
        self._previous_wakeup_fd: int | None = None
        self._sockets: tuple[socket.socket, socket.socket] | None = None
        self._notifier: QSocketNotifier | None = None

    # -- shutdown ----------------------------------------------------------------

    def run(self, *_args: Any) -> None:
        """Stop the per-key runtime (no restore), then turn the LEDs off; once only."""
        if self._ran:
            return
        self._ran = True
        logger.info("Turning lighting off for shutdown")
        self._stop_runtime()
        self._turn_off()

    def _stop_runtime(self) -> None:
        """Stop the per-key runtime without restoring hardware effects."""
        getter = self._runtime_getter or advanced_runtime.shared_runtime
        try:
            getter().shutdown(restore=False)
        except Exception:  # shutdown must go on
            logger.exception("Stopping the per-key runtime on shutdown failed")

    def _turn_off(self) -> None:
        """Turn every zone off when the daemon is connected."""
        try:
            if not self._service.connected:
                logger.info("Daemon not connected; leaving the lighting as it is")
                return
            lights_off.turn_off(self._service.devices)
        except Exception:  # shutdown must go on
            logger.exception("Turning the lighting off on shutdown failed")

    # -- wiring ------------------------------------------------------------------

    def install(self, app: Any) -> None:
        """Run on ``app``'s ``aboutToQuit`` and quit ``app`` on SIGTERM/SIGHUP/SIGINT."""
        self._app = app
        # Not commitDataRequest: it fires before a logout that can still be cancelled.
        about_to_quit = getattr(app, "aboutToQuit", None)
        if about_to_quit is None:
            logger.warning("Application has no aboutToQuit signal; not bound")
        else:
            about_to_quit.connect(self.run)
        if not callable(getattr(app, "quit", None)) or QCoreApplication.instance() is None:
            logger.warning("No running Qt application; quit signals not handled")
            return
        self._install_signals()

    def _install_signals(self) -> None:
        """Route QUIT_SIGNALS through a wakeup socket into the Qt event loop."""
        reader, writer = socket.socketpair()
        reader.setblocking(False)
        writer.setblocking(False)
        try:
            self._previous_wakeup_fd = signal.set_wakeup_fd(writer.fileno())
        except ValueError:  # not the main thread
            logger.warning("Cannot handle quit signals outside the main thread")
            reader.close()
            writer.close()
            return
        self._sockets = (reader, writer)
        self._notifier = QSocketNotifier(reader.fileno(), QSocketNotifier.Type.Read)
        self._notifier.activated.connect(self._on_wakeup)
        for signum in QUIT_SIGNALS:
            self._previous_handlers[signum] = signal.signal(signum, _ignore_signal)
        logger.info("Handling quit signals %s", [s.name for s in QUIT_SIGNALS])

    def _on_wakeup(self, *_args: Any) -> None:
        """Drain the wakeup socket and quit the application."""
        if self._sockets is None:
            return
        try:
            while self._sockets[0].recv(DRAIN_BYTES):
                pass
        except (BlockingIOError, InterruptedError):
            pass  # drained
        logger.info("Quit signal received; quitting")
        self._app.quit()

    def uninstall(self) -> None:
        """Restore the previous signal handlers and wakeup fd; close the sockets."""
        for signum, handler in self._previous_handlers.items():
            signal.signal(signum, handler)
        self._previous_handlers = {}
        if self._previous_wakeup_fd is not None:
            signal.set_wakeup_fd(self._previous_wakeup_fd)
            self._previous_wakeup_fd = None
        if self._notifier is not None:
            self._notifier.setEnabled(False)
            self._notifier = None
        if self._sockets is not None:
            for sock in self._sockets:
                sock.close()
            self._sockets = None
