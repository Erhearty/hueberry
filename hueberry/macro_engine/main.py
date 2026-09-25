# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Engine process entry point: arguments, logging, parent-death and signals.

The engine must never outlive Hueberry, because it holds exclusive grabs on
the user's input devices. Three independent mechanisms end it: the kernel
sends SIGTERM when the parent dies (prctl PR_SET_PDEATHSIG), a pidfd of the
parent becomes readable in the event loop, and as a last resort the loop
notices ``os.getppid()`` changed. Every exit path goes through
``EngineServer.close()``, which ungrabs all devices and removes the socket.
"""

import argparse
import ctypes
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any, Callable

from hueberry.macro_engine.server import AlreadyRunning, EngineServer
from hueberry.macros import protocol

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_ALREADY_RUNNING = 3
EXIT_NO_EVDEV = 4
PR_SET_PDEATHSIG = 1
PRCTL_OK = 0
STOP_SIGNALS = (signal.SIGTERM, signal.SIGINT)
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s [pid=%(process)d] %(message)s"
MSG_NO_EVDEV = ("python-evdev is not installed or not importable (%s); install the "
                "'macros' extra (pip install hueberry[macros]) or your distro's python3-evdev")


class ParentWatcher:
    """Tells whether the parent (Hueberry) is still alive.

    ``fileno()`` is a pidfd that turns readable when the parent exits (None
    where pidfd_open is unavailable); ``alive()`` compares ``getppid()``.
    """

    def __init__(
        self,
        parent_pid: int,
        getppid: Callable[[], int] = os.getppid,
        pidfd_open: Callable[[int], int] | None = getattr(os, "pidfd_open", None),
    ) -> None:
        self.parent_pid = parent_pid
        self._getppid = getppid
        self._fd: int | None = None
        if pidfd_open is not None:
            try:
                self._fd = pidfd_open(parent_pid)
            except OSError as exc:
                logger.info("pidfd_open(%d) failed (%s); polling getppid instead", parent_pid, exc)

    def fileno(self) -> int | None:
        """The parent's pidfd, or None."""
        return self._fd

    def alive(self) -> bool:
        """True while we are still the child of ``parent_pid`` (reparenting means it died)."""
        return self._getppid() == self.parent_pid

    def close(self) -> None:
        """Close the pidfd."""
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None


def set_parent_death_signal(sig: int = signal.SIGTERM) -> bool:
    """Best effort: have the kernel send ``sig`` when the parent dies (Linux)."""
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        result = libc.prctl(PR_SET_PDEATHSIG, int(sig), 0, 0, 0)
    except (OSError, AttributeError) as exc:
        logger.info("prctl unavailable: %s", exc)
        return False
    if result != PRCTL_OK:
        logger.info("prctl(PR_SET_PDEATHSIG) failed: errno %d", ctypes.get_errno())
        return False
    return True


def install_signal_handlers(server: Any) -> dict:
    """Route SIGTERM/SIGINT to ``server.request_stop``; returns previous handlers."""
    def _handler(signum: int, _frame: Any) -> None:
        server.request_stop(f"signal {signal.Signals(signum).name}")

    return {sig: signal.signal(sig, _handler) for sig in STOP_SIGNALS}


def restore_signal_handlers(previous: dict) -> None:
    """Undo ``install_signal_handlers``."""
    for sig, handler in previous.items():
        signal.signal(sig, handler)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the command line; ``--parent-pid`` is mandatory."""
    parser = argparse.ArgumentParser(
        prog="python -m hueberry.macro_engine",
        description="Hueberry macro engine (started by Hueberry, not by users).",
    )
    parser.add_argument("--parent-pid", type=int, required=True, help="exit when this process exits")
    parser.add_argument("--socket", type=Path, default=None, help="IPC socket path (default: per-user runtime dir)")
    parser.add_argument("--verbose", action="store_true", help="debug logging")
    return parser.parse_args(argv)


def configure_logging(verbose: bool) -> None:
    """Structured, timestamped logs on stderr (Hueberry captures them)."""
    logging.basicConfig(stream=sys.stderr, level=logging.DEBUG if verbose else logging.INFO, format=LOG_FORMAT)


def evdev_available() -> bool:
    """True when python-evdev imports; logs how to install it otherwise."""
    try:
        import evdev  # noqa: F401 - availability check only
    except ImportError as exc:
        logger.error(MSG_NO_EVDEV, exc)
        return False
    return True


def run_server(server: Any) -> int:
    """Serve until stopped; map outcomes to exit codes (cleanup is in serve())."""
    previous = install_signal_handlers(server)
    try:
        server.serve()
    except AlreadyRunning as exc:
        logger.info("%s; exiting", exc)
        return EXIT_ALREADY_RUNNING
    except Exception:
        logger.exception("Macro engine crashed; all devices were released")
        return EXIT_ERROR
    finally:
        restore_signal_handlers(previous)
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """Run the engine as a child of ``--parent-pid``; returns the exit code."""
    args = parse_args(argv)
    configure_logging(args.verbose)
    if not evdev_available():
        return EXIT_NO_EVDEV
    set_parent_death_signal()
    watcher = ParentWatcher(args.parent_pid)
    try:
        if not watcher.alive():
            logger.info("Parent %d is already gone; not starting", args.parent_pid)
            return EXIT_OK
        path = args.socket if args.socket is not None else protocol.socket_path()
        return run_server(EngineServer(path, parent_watcher=watcher))
    finally:
        watcher.close()
