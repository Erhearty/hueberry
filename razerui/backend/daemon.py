# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 RazerUI contributors
"""Connection to, and lifecycle control of, the OpenRazer daemon."""

import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

DAEMON_EXECUTABLE = "openrazer-daemon"
PID_FILE_NAME = "openrazer-daemon.pid"
RUNTIME_DIR_FALLBACK = "/run/user/{uid}"
SYSTEMD_UNIT = "openrazer-daemon"
SYSTEMCTL_IS_ACTIVE = ["systemctl", "--user", "is-active", SYSTEMD_UNIT]
SYSTEMCTL_RESTART = ["systemctl", "--user", "restart", SYSTEMD_UNIT]
DAEMON_STOP_CMD = [DAEMON_EXECUTABLE, "-s"]
DAEMON_KILL_CMD = ["killall", DAEMON_EXECUTABLE]
DAEMON_START_CMD = [DAEMON_EXECUTABLE]
COMMAND_TIMEOUT_S = 10
STOP_WAIT_S = 2.0
START_WAIT_S = 2.0
CONNECT_RETRIES = 3
CONNECT_RETRY_DELAY_S = 1.0
RETURNCODE_OK = 0
MSG_NOT_INSTALLED = "python3-openrazer not installed or not importable"
MSG_NOT_CONNECTED = "Not connected to the OpenRazer daemon"
MSG_NO_EXECUTABLE = "openrazer-daemon executable not found"


def default_pid_path() -> Path:
    """Return the daemon pid file path ($XDG_RUNTIME_DIR, else /run/user/<uid>)."""
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR") or RUNTIME_DIR_FALLBACK.format(uid=os.getuid())
    return Path(runtime_dir) / PID_FILE_NAME


def pid_alive(pid: int) -> bool:
    """True when a process with ``pid`` exists (signal 0; EPERM still means alive)."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except (ProcessLookupError, OverflowError, OSError):
        return False
    return True


@dataclass(frozen=True)
class DaemonStatus:
    """Snapshot of the daemon state; settings are None when not connected."""

    running: bool
    daemon_version: str | None = None
    client_version: str | None = None
    sync_effects: bool | None = None
    turn_off_on_screensaver: bool | None = None


class DaemonService:
    """Wraps ``openrazer.client.DeviceManager`` plus daemon start/stop/restart.

    ``run``, ``popen``, ``sleep``, ``which``, ``pid_path`` and ``is_alive`` are
    injectable so the service can be tested without real processes or delays.
    """

    def __init__(
        self,
        *,
        run: Callable[..., Any] = subprocess.run,
        popen: Callable[..., Any] = subprocess.Popen,
        sleep: Callable[[float], None] = time.sleep,
        which: Callable[[str], str | None] = shutil.which,
        pid_path: Path | None = None,
        is_alive: Callable[[int], bool] = pid_alive,
    ) -> None:
        self._run = run
        self._popen = popen
        self._sleep = sleep
        self._which = which
        self._pid_path = pid_path
        self._is_alive = is_alive
        self._manager: Any = None
        self.last_error: str | None = None

    # -- connection ---------------------------------------------------------

    @property
    def connected(self) -> bool:
        """True when a DeviceManager is currently held."""
        return self._manager is not None

    @property
    def manager(self) -> Any:
        """The cached DeviceManager, or None."""
        return self._manager

    @property
    def devices(self) -> list:
        """Devices known to the cached manager ([] when not connected)."""
        if self._manager is None:
            return []
        try:
            return list(self._manager.devices)
        except Exception:  # D-Bus errors surface as arbitrary exceptions
            logger.exception("Failed to read device list")
            return []

    def _fail(self, message: str) -> bool:
        self.last_error = message
        logger.warning(message)
        return False

    def connect(self) -> bool:
        """Create a DeviceManager; returns False and sets last_error on failure."""
        self._manager = None
        try:
            import openrazer.client as client  # lazy: distro package, optional
        except ImportError as exc:  # also a missing dbus or a venv without system packages
            return self._fail(f"{MSG_NOT_INSTALLED} ({exc})")
        try:
            self._manager = client.DeviceManager()
        except client.DaemonNotFound as exc:
            return self._fail(f"OpenRazer daemon not found: {exc}")
        except Exception as exc:  # D-Bus failures are not typed consistently
            return self._fail(f"Could not connect to OpenRazer daemon: {exc}")
        self.last_error = None
        logger.info("Connected to OpenRazer daemon")
        return True

    def repoll(self) -> bool:
        """Drop the cached manager (its device list is fixed) and reconnect."""
        self._manager = None
        return self.connect()

    # -- status and settings -----------------------------------------------

    def _pid_file_running(self) -> bool:
        """True when the pid file names a live process (a stale file means stopped)."""
        path = self._pid_path if self._pid_path is not None else default_pid_path()
        try:
            pid = int(path.read_text(encoding="ascii").strip())
        except FileNotFoundError:
            return False
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            logger.warning("Cannot read pid file %s: %s", path, exc)
            return False
        return self._is_alive(pid)

    def _read(self, attr: str) -> Any:
        try:
            return getattr(self._manager, attr)
        except Exception:  # D-Bus errors
            logger.exception("Failed to read daemon attribute %s", attr)
            return None

    def status(self) -> DaemonStatus:
        """Return a DaemonStatus snapshot."""
        if self._manager is None:
            return DaemonStatus(running=self._pid_file_running())
        return DaemonStatus(
            running=True,
            daemon_version=self._read("daemon_version"),
            client_version=self._read("version"),
            sync_effects=self._read("sync_effects"),
            turn_off_on_screensaver=self._read("turn_off_on_screensaver"),
        )

    def _set(self, attr: str, value: bool) -> bool:
        if self._manager is None:
            return self._fail(MSG_NOT_CONNECTED)
        try:
            setattr(self._manager, attr, bool(value))
        except Exception as exc:  # D-Bus / ValueError
            return self._fail(f"Failed to set {attr}: {exc}")
        return True

    def set_sync_effects(self, enabled: bool) -> bool:
        """Enable or disable effect syncing across devices."""
        return self._set("sync_effects", enabled)

    def set_screensaver_off(self, enabled: bool) -> bool:
        """Enable or disable turning devices off while the screensaver is active."""
        return self._set("turn_off_on_screensaver", enabled)

    # -- lifecycle -----------------------------------------------------------

    def stop(self) -> bool:
        """Ask the daemon to stop via D-Bus, then drop the manager."""
        manager = self._manager
        if manager is None:
            return self._fail(MSG_NOT_CONNECTED)
        try:
            manager.stop_daemon()
        except Exception as exc:  # D-Bus errors
            return self._fail(f"Failed to stop daemon: {exc}")
        finally:
            self._manager = None
        return True

    def start(self) -> bool:
        """Launch ``openrazer-daemon`` (no shell); returns False on failure."""
        if self._which(DAEMON_EXECUTABLE) is None:
            return self._fail(MSG_NO_EXECUTABLE)
        try:
            self._popen(
                list(DAEMON_START_CMD),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            return self._fail(f"Failed to start daemon: {exc}")
        return True

    def start_and_connect(self) -> bool:
        """Launch the daemon, wait START_WAIT_S, then connect with bounded retries."""
        if not self.start():
            return False
        self._sleep(START_WAIT_S)
        return self._connect_with_retries()

    def _run_command(self, args: list[str]) -> Any:
        """Run a command; return its result, or None if it could not run."""
        try:
            return self._run(
                list(args), check=False, capture_output=True, text=True, timeout=COMMAND_TIMEOUT_S
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("Command %s failed: %s", args, exc)
            return None

    def _systemd_active(self) -> bool:
        result = self._run_command(SYSTEMCTL_IS_ACTIVE)
        return result is not None and result.returncode == RETURNCODE_OK

    def _restart_systemd(self) -> bool:
        result = self._run_command(SYSTEMCTL_RESTART)
        if result is None or result.returncode != RETURNCODE_OK:
            return self._fail("systemctl restart of openrazer-daemon failed")
        return True

    def _restart_manual(self) -> bool:
        if self._which(DAEMON_EXECUTABLE) is None:  # never kill what we cannot restart
            return self._fail(MSG_NO_EXECUTABLE)
        self._run_command(DAEMON_STOP_CMD)
        self._sleep(STOP_WAIT_S)
        self._run_command(DAEMON_KILL_CMD)  # non-zero when nothing to kill
        started = self.start()
        self._sleep(START_WAIT_S)
        return started

    def _connect_with_retries(self) -> bool:
        for attempt in range(1, CONNECT_RETRIES + 1):
            if self.connect():
                return True
            logger.info("Reconnect attempt %d/%d failed", attempt, CONNECT_RETRIES)
            if attempt < CONNECT_RETRIES:
                self._sleep(CONNECT_RETRY_DELAY_S)
        return False

    def restart(self) -> bool:
        """Restart the daemon (systemd user unit if active, else manually) and reconnect."""
        self._manager = None
        if self._systemd_active():
            restarted = self._restart_systemd()
        else:
            restarted = self._restart_manual()
        if not restarted:
            return False
        return self._connect_with_retries()
