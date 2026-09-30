# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Start, stop and reconfigure the Waybar process that draws the sysmon overlay.

``SysmonController`` owns one ``waybar`` child (its own session/process
group), records its pid in ``$XDG_RUNTIME_DIR/hueberry/sysmon.pid`` and keeps
the persisted ``enabled`` flag in sync. Every side effect is injectable so the
controller can be tested without spawning processes. Errors are logged and
stored in ``last_error``; they are never raised to the UI.
"""

import dataclasses
import logging
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import QObject, pyqtSignal

from hueberry.backend.daemon import pid_alive
from hueberry.gui_link import app_runtime_dir
from hueberry.sysmon import config as sysmon_config
from hueberry.sysmon import waybar
from hueberry.sysmon.config import SysmonConfig, SysmonConfigError

logger = logging.getLogger(__name__)

WAYBAR_EXECUTABLE = "waybar"
PID_FILE_NAME = "sysmon.pid"
PID_DIR_MODE = 0o700
PROC_ROOT = Path("/proc")
CMDLINE_FILE = "cmdline"
CMDLINE_SEPARATOR = b"\0"
STOP_TIMEOUT_S = 2.0
STOP_POLL_S = 0.1
STOP_POLL_STEPS = round(STOP_TIMEOUT_S / STOP_POLL_S)
REAP_TIMEOUT_S = 0.5
MSG_NO_WAYBAR = "waybar not found"


def default_pid_path() -> Path:
    """``$XDG_RUNTIME_DIR/hueberry/sysmon.pid``."""
    return app_runtime_dir() / PID_FILE_NAME


def read_cmdline(pid: int, proc_root: Path = PROC_ROOT) -> list[str]:
    """Arguments of process ``pid`` from ``/proc/<pid>/cmdline`` ([] if unreadable)."""
    try:
        raw = (proc_root / str(pid) / CMDLINE_FILE).read_bytes()
    except OSError:
        return []
    return [part.decode(errors="replace") for part in raw.split(CMDLINE_SEPARATOR) if part]


class SysmonController(QObject):
    """Lifecycle of the Waybar overlay process plus its persisted configuration."""

    state_changed = pyqtSignal(bool)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        popen: Callable[..., Any] = subprocess.Popen,
        which: Callable[[str], str | None] = shutil.which,
        killpg: Callable[[int, int], None] = os.killpg,
        is_alive: Callable[[int], bool] = pid_alive,
        sleep: Callable[[float], None] = time.sleep,
        read_cmdline: Callable[[int], list[str]] = read_cmdline,
        pid_path: Path | None = None,
        config_path: Path | None = None,
        out_dir: Path | None = None,
        load: Callable[..., SysmonConfig] = sysmon_config.load,
        save: Callable[..., None] = sysmon_config.save,
        write_files: Callable[..., tuple[Path, Path]] = waybar.write_files,
    ) -> None:
        super().__init__(parent)
        self._popen, self._which, self._killpg = popen, which, killpg
        self._is_alive, self._sleep, self._read_cmdline = is_alive, sleep, read_cmdline
        self._pid_path = pid_path if pid_path is not None else default_pid_path()
        self._config_path = config_path if config_path is not None else sysmon_config.config_path()
        self._out_dir = out_dir if out_dir is not None else waybar.default_out_dir()
        self._save, self._write_files = save, write_files
        self._proc: Any = None
        self.last_error: str | None = None
        self._config: SysmonConfig = load(self._config_path)

    # -- public API ---------------------------------------------------------

    @property
    def config(self) -> SysmonConfig:
        """The current configuration."""
        return self._config

    def is_running(self) -> bool:
        """True while the Waybar child started by this controller is alive."""
        proc = self._proc
        return proc is not None and proc.poll() is None and self._is_alive(proc.pid)

    def start(self) -> bool:
        """Launch Waybar, persist ``enabled=True`` and emit; False on failure."""
        if self.is_running():
            return True
        if not self._launch():
            return False
        self._persist_enabled(True)
        self.state_changed.emit(True)
        return True

    def stop(self) -> None:
        """Terminate Waybar, persist ``enabled=False`` and emit."""
        self._terminate()
        self._persist_enabled(False)
        self.state_changed.emit(False)

    def toggle(self) -> bool:
        """Stop when running, else start; returns the new running state."""
        if self.is_running():
            self.stop()
        else:
            self.start()
        return self.is_running()

    def apply(self, new_cfg: SysmonConfig) -> list[str]:
        """Save and apply ``new_cfg`` (keeping ``enabled``); returns its problems.

        With problems nothing changes. Otherwise the Waybar files are rewritten
        and a running overlay is restarted to pick them up.
        """
        found = new_cfg.problems()
        if found:
            return found
        cfg = dataclasses.replace(new_cfg, enabled=self._config.enabled)
        self._store(cfg)
        self._config = cfg
        if self.is_running():
            self._restart()
        else:
            self._write_waybar_files()
        return []

    def restore(self) -> bool:
        """Start the overlay when the stored config says it is enabled (app launch)."""
        if not self._config.enabled:
            return False
        return self.start()

    def shutdown(self) -> None:
        """Stop Waybar without touching the persisted ``enabled`` flag (app quit)."""
        was_running = self.is_running()
        self._terminate()
        if was_running:
            self.state_changed.emit(False)

    # -- helpers ------------------------------------------------------------

    def _fail(self, message: str) -> bool:
        self.last_error = message
        logger.warning("Sysmon: %s", message)
        return False

    def _waybar_config_path(self) -> Path:
        return self._out_dir / waybar.WAYBAR_CONFIG_NAME

    def _write_waybar_files(self) -> tuple[Path, Path] | None:
        """Write the Waybar config and style; None (and last_error) on failure."""
        try:
            return self._write_files(self._config, self._config_path, self._out_dir)
        except OSError as exc:
            self._fail(f"Failed to write Waybar files: {exc}")
            return None

    def _store(self, cfg: SysmonConfig) -> None:
        """Persist ``cfg``; failures only set last_error."""
        try:
            self._save(cfg, self._config_path)
        except (OSError, SysmonConfigError) as exc:
            self._fail(f"Failed to save sysmon config: {exc}")

    def _persist_enabled(self, enabled: bool) -> None:
        if self._config.enabled == enabled:
            return
        self._config = dataclasses.replace(self._config, enabled=enabled)
        self._store(self._config)

    def _restart(self) -> None:
        """Relaunch a running overlay; emits False if it could not come back."""
        self._terminate()
        if not self._launch():
            self.state_changed.emit(False)

    def _launch(self) -> bool:
        """Clear a stale instance, write files and spawn Waybar; records the pid."""
        if self._which(WAYBAR_EXECUTABLE) is None:
            return self._fail(MSG_NO_WAYBAR)
        self._clear_stale()
        paths = self._write_waybar_files()
        if paths is None:
            return False
        waybar_path, style_path = paths
        args = [WAYBAR_EXECUTABLE, "-c", str(waybar_path), "-s", str(style_path)]
        try:
            self._proc = self._popen(
                args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True,
            )
        except OSError as exc:
            return self._fail(f"Failed to start waybar: {exc}")
        logger.info("Started waybar sysmon overlay (pid %d)", self._proc.pid)
        self.last_error = None
        self._write_pid(self._proc.pid)
        return True

    # -- process handling ---------------------------------------------------

    def _terminate(self) -> None:
        """Stop our Waybar child (if any), reap it and remove the pid file."""
        proc, self._proc = self._proc, None
        if proc is not None:
            self._kill_group(proc.pid, lambda: proc.poll() is None and self._is_alive(proc.pid))
            self._reap(proc)
        self._remove_pid_file()

    def _signal_group(self, pid: int, sig: int) -> bool:
        """Send ``sig`` to process group ``pid``; False when it is already gone."""
        try:
            self._killpg(pid, sig)
        except ProcessLookupError:
            return False
        except OSError as exc:
            logger.warning("Cannot signal process group %d: %s", pid, exc)
            return False
        return True

    def _kill_group(self, pid: int, alive: Callable[[], bool]) -> None:
        """SIGTERM, wait up to STOP_TIMEOUT_S, then SIGKILL if still alive."""
        if not self._signal_group(pid, signal.SIGTERM):
            return
        for _ in range(STOP_POLL_STEPS):
            if not alive():
                return
            self._sleep(STOP_POLL_S)
        if alive():
            logger.warning("waybar (pid %d) ignored SIGTERM; sending SIGKILL", pid)
            self._signal_group(pid, signal.SIGKILL)

    @staticmethod
    def _reap(proc: Any) -> None:
        """Collect the child's exit status so it does not linger as a zombie."""
        if proc.poll() is not None:
            return
        try:
            proc.wait(timeout=REAP_TIMEOUT_S)
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("Could not reap waybar (pid %d): %s", proc.pid, exc)

    def _is_our_waybar(self, pid: int) -> bool:
        """True when ``pid`` is a Waybar running our generated config."""
        args = self._read_cmdline(pid)
        if not args or os.path.basename(args[0]) != WAYBAR_EXECUTABLE:
            return False
        return str(self._waybar_config_path()) in args

    def _clear_stale(self) -> None:
        """Kill a leftover overlay named by the pid file (only if it is ours)."""
        pid = self._read_pid()
        if pid is not None and self._is_alive(pid):
            if self._is_our_waybar(pid):
                logger.info("Stopping stale waybar sysmon overlay (pid %d)", pid)
                self._kill_group(pid, lambda: self._is_alive(pid))
            else:
                logger.info("Ignoring stale sysmon pid %d (not our waybar)", pid)
        self._remove_pid_file()

    # -- pid file -----------------------------------------------------------

    def _read_pid(self) -> int | None:
        try:
            pid = int(self._pid_path.read_text(encoding="ascii").strip())
        except FileNotFoundError:
            return None
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            logger.warning("Cannot read pid file %s: %s", self._pid_path, exc)
            return None
        return pid if pid > 0 else None

    def _write_pid(self, pid: int) -> None:
        try:
            self._pid_path.parent.mkdir(mode=PID_DIR_MODE, parents=True, exist_ok=True)
            self._pid_path.write_text(f"{pid}\n", encoding="ascii")
        except OSError as exc:
            logger.warning("Cannot write pid file %s: %s", self._pid_path, exc)

    def _remove_pid_file(self) -> None:
        try:
            self._pid_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Cannot remove pid file %s: %s", self._pid_path, exc)
