# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Lifecycle of the macro engine child process, plus a client for talking to it.

Hueberry starts ``python -m hueberry.macro_engine --parent-pid <our pid>`` and
waits until it answers ``ping``. An engine that is already running (exit
code 3) is adopted rather than fought over; one that exits with code 4 tells
us python-evdev is missing. ``popen``, ``sleep`` and ``client`` are injectable
so the service is testable without real processes or delays.
"""

import logging
import os
import subprocess
import sys
import threading
import time
from typing import Any, Callable

from hueberry.macros import protocol
from hueberry.macros.protocol import EngineClient, EngineError, EngineUnavailable

logger = logging.getLogger(__name__)

ENGINE_MODULE = "hueberry.macro_engine"
PARENT_PID_FLAG = "--parent-pid"
# Exit codes of hueberry.macro_engine.main (kept in sync by a test).
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_ALREADY_RUNNING = 3
EXIT_NO_EVDEV = 4
READY_POLL_S = 0.1
READY_ATTEMPTS = 50  # READY_POLL_S * READY_ATTEMPTS = 5 s to come up
STOP_TIMEOUT_S = 2.0

STATE_STOPPED = "stopped"
STATE_STARTING = "starting"
STATE_RUNNING = "running"
STATE_CRASHED = "crashed"
STATE_EVDEV_MISSING = "evdev_missing"
STATE_UNAVAILABLE = "unavailable"

MSG_NO_EVDEV = "python-evdev is not installed; macros are unavailable"
MSG_NOT_READY = "the macro engine did not answer in time"


class MacroEngineService:
    """Starts, watches and stops the engine, and forwards requests to it.

    ``state`` is one of the ``STATE_*`` constants; ``last_error`` explains a
    failure. ``start`` = ``spawn`` + ``wait_ready``. The UI must call ``spawn`` on the
    GUI thread (the engine's PR_SET_PDEATHSIG fires when the *forking thread*
    exits) and run only the blocking ``wait_ready`` through ``worker.run_async``.
    """

    def __init__(
        self,
        *,
        popen: Callable[..., Any] = subprocess.Popen,
        sleep: Callable[[float], None] = time.sleep,
        client: Any = None,
        python: str = sys.executable,
        parent_pid: int | None = None,
    ) -> None:
        self._popen = popen
        self._sleep = sleep
        self._client = client if client is not None else EngineClient(protocol.socket_path())
        self._python = python
        self._parent_pid = parent_pid if parent_pid is not None else os.getpid()
        self._lock = threading.Lock()
        self._process: Any = None
        self._stop_requested = False
        self.adopted = False
        self.state = STATE_STOPPED
        self.last_error: str | None = None

    # -- lifecycle -------------------------------------------------------------

    def command(self) -> list[str]:
        """The argv used to spawn the engine (no shell)."""
        return [self._python, "-m", ENGINE_MODULE, PARENT_PID_FLAG, str(self._parent_pid)]

    def start(self) -> bool:
        """Spawn the engine (or adopt a running one) and wait until it answers."""
        return self.spawn() and self.wait_ready()

    def spawn(self) -> bool:
        """Non-blocking: start the child unless ours is still alive; False if Popen failed.

        Call it on a long-lived thread (the GUI thread): the engine asks the
        kernel for SIGTERM when the thread that forked it exits.
        """
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return True
            self._stop_requested = False
            self.adopted = False
            try:
                self._process = self._popen(self.command(), stdin=subprocess.DEVNULL,
                                            stdout=subprocess.DEVNULL)
            except OSError as exc:
                return self._fail(STATE_CRASHED, f"Cannot start the macro engine: {exc}")
            self.state = STATE_STARTING
            logger.info("Macro engine started (pid %s)", getattr(self._process, "pid", "?"))
        return True

    def wait_ready(self) -> bool:
        """Blocking: wait until the spawned engine answers ``ping`` (safe on a worker)."""
        if self.state == STATE_RUNNING or self._process is None:
            return self.state == STATE_RUNNING
        return self._wait_ready()

    def _wait_ready(self) -> bool:
        for _attempt in range(READY_ATTEMPTS):
            if self._stop_requested:
                return False
            process = self._process  # stop() may clear it from the GUI thread
            code = process.poll() if process is not None else None
            if code is not None:
                return self._on_exit(code)
            if self._ping():
                return self._set_running()
            self._sleep(READY_POLL_S)
        return self._fail(STATE_UNAVAILABLE, MSG_NOT_READY)

    def _on_exit(self, code: int) -> bool:
        self._process = None
        if code == EXIT_ALREADY_RUNNING and self._ping():
            logger.info("Adopting the macro engine that is already running")
            self.adopted = True
            return self._set_running()
        if code == EXIT_NO_EVDEV:
            return self._fail(STATE_EVDEV_MISSING, MSG_NO_EVDEV)
        return self._fail(STATE_CRASHED, f"The macro engine exited with code {code}")

    def _ping(self) -> bool:
        try:
            self._client.request(protocol.OP_PING)
        except (EngineUnavailable, EngineError):
            return False
        return True

    def _set_running(self) -> bool:
        self.state = STATE_RUNNING
        self.last_error = None
        return True

    def _fail(self, state: str, message: str) -> bool:
        self.state = state
        self.last_error = message
        logger.warning("Macro engine: %s", message)
        return False

    def stop(self) -> None:
        """Terminate our engine; kill it after STOP_TIMEOUT_S. An adopted one is left alone."""
        self._stop_requested = True
        process, self._process = self._process, None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=STOP_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                logger.warning("Macro engine ignored SIGTERM; killing it")
                process.kill()
                process.wait()
        self.adopted = False
        self.state = STATE_STOPPED
        logger.info("Macro engine stopped")

    def poll(self) -> str:
        """Notice a crashed child and return the current state."""
        process = self._process
        if process is not None and self.state == STATE_RUNNING:
            code = process.poll()
            if code is not None:
                self._process = None
                self._fail(STATE_CRASHED, f"The macro engine exited with code {code}")
        return self.state

    # -- requests ----------------------------------------------------------------

    def request(self, op: str, **args: Any) -> dict:
        """Forward one request; EngineUnavailable also updates ``state``."""
        try:
            return self._client.request(op, **args)
        except EngineUnavailable as exc:
            if self.poll() == STATE_RUNNING:
                self._fail(STATE_UNAVAILABLE, str(exc))
            raise

    def status(self) -> dict:
        """The engine's ``status`` result."""
        return self.request(protocol.OP_STATUS)

    def list_devices(self) -> dict:
        """The engine's ``list_devices`` result (devices and permissions)."""
        return self.request(protocol.OP_LIST_DEVICES)

    def reload(self) -> dict:
        """Ask the engine to re-read macros.json; returns the new status."""
        return self.request(protocol.OP_RELOAD)

    def record_start(self, identity: str) -> dict:
        """Start recording key events of ``identity``."""
        return self.request(protocol.OP_RECORD_START, identity=identity)

    def record_stop(self) -> dict:
        """Stop recording; the result holds ``events`` as ``[[code, value, t], ...]``."""
        return self.request(protocol.OP_RECORD_STOP)
