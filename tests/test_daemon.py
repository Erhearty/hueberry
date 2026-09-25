# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for hueberry.backend.daemon (no real subprocesses or sleeping)."""

import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from hueberry.backend import daemon as daemon_mod
from hueberry.backend.daemon import DaemonService, default_pid_path, pid_alive

NONEXISTENT_PID = 2**22 + 12345  # above the Linux pid_max ceiling (2**22)


class FakeRunner:
    """Records subprocess.run calls; returncode chosen per command."""

    def __init__(self, systemd_active: bool) -> None:
        self.systemd_active = systemd_active
        self.calls: list[list[str]] = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        assert "timeout" in kwargs
        is_active = args == daemon_mod.SYSTEMCTL_IS_ACTIVE
        code = 0 if (not is_active or self.systemd_active) else 3
        return subprocess.CompletedProcess(args, code, "", "")


@pytest.fixture
def recorder():
    """Namespace collecting popen and sleep calls."""
    rec = SimpleNamespace(popen=[], sleeps=[])
    rec.popen_fn = lambda args, **kw: rec.popen.append(args)
    rec.sleep_fn = rec.sleeps.append
    return rec


def make_service(tmp_path, recorder, runner=None, which=lambda name: "/usr/bin/" + name):
    """Service with every side effect faked; pid file lives under tmp_path."""
    return DaemonService(
        run=runner or FakeRunner(systemd_active=False),
        popen=recorder.popen_fn,
        sleep=recorder.sleep_fn,
        which=which,
        pid_path=tmp_path / "openrazer-daemon.pid",
    )


def test_connect_succeeds(tmp_path, recorder, fake_manager_factory, make_device):
    """A reachable daemon yields devices and a full status."""
    fake_manager_factory.devices = [make_device()]
    svc = make_service(tmp_path, recorder)
    assert svc.connect() is True
    assert svc.last_error is None
    assert len(svc.devices) == 1
    status = svc.status()
    assert status.running is True
    assert status.daemon_version == "3.12.1-fake"
    assert status.client_version == "3.12.1"
    assert status.sync_effects is False
    assert status.turn_off_on_screensaver is False


def test_daemon_not_found(tmp_path, recorder, fake_manager_factory):
    """DaemonNotFound: not running (no pid file), last_error set."""
    fake_manager_factory.fail = True
    svc = make_service(tmp_path, recorder)
    assert svc.connect() is False
    assert "not found" in svc.last_error
    assert svc.devices == []
    status = svc.status()
    assert status.running is False
    assert status.daemon_version is None
    assert status.sync_effects is None


def test_pid_file_means_running(tmp_path, recorder, fake_manager_factory):
    """Without a connection, a pid file naming a live process reports running."""
    fake_manager_factory.fail = True
    (tmp_path / "openrazer-daemon.pid").write_text(f"{os.getpid()}\n")
    svc = make_service(tmp_path, recorder)
    svc.connect()
    assert svc.status().running is True


@pytest.mark.parametrize("content", ["garbage", "", str(NONEXISTENT_PID), "-5"])
def test_stale_or_bad_pid_file_means_stopped(tmp_path, recorder, content):
    """A garbage, empty, negative or dead pid in the pid file reports not running."""
    (tmp_path / "openrazer-daemon.pid").write_text(content)
    svc = make_service(tmp_path, recorder)
    assert svc.status().running is False


def test_pid_liveness_is_injectable(tmp_path, recorder):
    """The liveness check receives the parsed pid."""
    (tmp_path / "pid").write_text("4242")
    seen = []
    svc = DaemonService(pid_path=tmp_path / "pid", is_alive=lambda pid: seen.append(pid) or True)
    assert svc.status().running is True
    assert seen == [4242]


def test_pid_alive():
    """The current process is alive; a nonexistent pid is not."""
    assert pid_alive(os.getpid()) is True
    assert pid_alive(NONEXISTENT_PID) is False
    assert pid_alive(0) is False


def test_default_pid_path_uses_xdg_runtime_dir(tmp_path, monkeypatch):
    """$XDG_RUNTIME_DIR is used for the pid file when set."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert default_pid_path() == tmp_path / "openrazer-daemon.pid"


def test_import_error(tmp_path, recorder, monkeypatch):
    """A missing openrazer client gives a clear message."""
    monkeypatch.setitem(sys.modules, "openrazer.client", None)
    svc = make_service(tmp_path, recorder)
    assert svc.connect() is False
    assert svc.last_error.startswith("python3-openrazer not installed or not importable (")
    assert svc.last_error.endswith(")")
    assert len(svc.last_error) > len("python3-openrazer not installed or not importable ()")


def test_repoll_creates_new_manager(tmp_path, recorder, fake_manager_factory, make_device):
    """repoll() rebuilds the manager so new devices show up."""
    svc = make_service(tmp_path, recorder)
    svc.connect()
    assert svc.devices == []
    fake_manager_factory.devices = [make_device()]
    assert svc.repoll() is True
    assert fake_manager_factory.constructions == 2
    assert svc.manager is fake_manager_factory.instances[-1]
    assert len(svc.devices) == 1


def test_settings(tmp_path, recorder):
    """Settings are written to the manager; fail when disconnected."""
    svc = make_service(tmp_path, recorder)
    assert svc.set_sync_effects(True) is False
    svc.connect()
    assert svc.set_sync_effects(True) is True
    assert svc.set_screensaver_off(True) is True
    assert svc.manager.sync_effects is True
    assert svc.manager.turn_off_on_screensaver is True


def test_stop_calls_stop_daemon(tmp_path, recorder):
    """stop() asks the daemon to stop and drops the manager."""
    svc = make_service(tmp_path, recorder)
    svc.connect()
    manager = svc.manager
    assert svc.stop() is True
    assert manager.stop_calls == 1
    assert svc.manager is None


def test_start_and_connect(tmp_path, recorder, fake_manager_factory):
    """start_and_connect() launches, waits via the injected sleep, then connects."""
    svc = make_service(tmp_path, recorder)
    assert svc.start_and_connect() is True
    assert recorder.popen == [["openrazer-daemon"]]
    assert recorder.sleeps == [daemon_mod.START_WAIT_S]
    assert svc.connected


def test_start_and_connect_retries(tmp_path, recorder, fake_manager_factory):
    """A daemon that never answers is retried CONNECT_RETRIES times."""
    fake_manager_factory.fail = True
    svc = make_service(tmp_path, recorder)
    assert svc.start_and_connect() is False
    assert fake_manager_factory.constructions == daemon_mod.CONNECT_RETRIES
    assert recorder.sleeps == [daemon_mod.START_WAIT_S] + [
        daemon_mod.CONNECT_RETRY_DELAY_S] * (daemon_mod.CONNECT_RETRIES - 1)


def test_start_and_connect_without_executable(tmp_path, recorder, fake_manager_factory):
    """No executable: nothing launched, no sleep, no connect attempt."""
    svc = make_service(tmp_path, recorder, which=lambda name: None)
    assert svc.start_and_connect() is False
    assert recorder.popen == [] and recorder.sleeps == []
    assert fake_manager_factory.constructions == 0


def test_restart_manual_without_executable_kills_nothing(tmp_path, recorder):
    """Missing openrazer-daemon: no -s/killall, last_error set, restart fails."""
    runner = FakeRunner(systemd_active=False)
    svc = make_service(tmp_path, recorder, runner=runner, which=lambda name: None)
    assert svc.restart() is False
    assert runner.calls == [daemon_mod.SYSTEMCTL_IS_ACTIVE]
    assert svc.last_error == daemon_mod.MSG_NO_EXECUTABLE
    assert recorder.popen == [] and recorder.sleeps == []


def test_start_without_executable(tmp_path, recorder):
    """start() fails cleanly when openrazer-daemon is not on PATH."""
    svc = make_service(tmp_path, recorder, which=lambda name: None)
    assert svc.start() is False
    assert svc.last_error == "openrazer-daemon executable not found"
    assert recorder.popen == []


def test_restart_systemd(tmp_path, recorder, fake_manager_factory):
    """An active user unit is restarted via systemctl."""
    runner = FakeRunner(systemd_active=True)
    svc = make_service(tmp_path, recorder, runner=runner)
    assert svc.restart() is True
    assert runner.calls == [
        ["systemctl", "--user", "is-active", "openrazer-daemon"],
        ["systemctl", "--user", "restart", "openrazer-daemon"],
    ]
    assert recorder.popen == []
    assert fake_manager_factory.constructions == 1


def test_restart_fallback_sequence(tmp_path, recorder, fake_manager_factory):
    """Without systemd: -s, sleep, killall, start, sleep, reconnect."""
    runner = FakeRunner(systemd_active=False)
    svc = make_service(tmp_path, recorder, runner=runner)
    assert svc.restart() is True
    assert runner.calls == [
        ["systemctl", "--user", "is-active", "openrazer-daemon"],
        ["openrazer-daemon", "-s"],
        ["killall", "openrazer-daemon"],
    ]
    assert recorder.popen == [["openrazer-daemon"]]
    assert recorder.sleeps == [daemon_mod.STOP_WAIT_S, daemon_mod.START_WAIT_S]


def test_restart_retries_connect(tmp_path, recorder, fake_manager_factory):
    """Reconnect is retried a bounded number of times."""
    fake_manager_factory.fail = True
    svc = make_service(tmp_path, recorder)
    assert svc.restart() is False
    assert fake_manager_factory.constructions == daemon_mod.CONNECT_RETRIES
    retry_sleeps = [s for s in recorder.sleeps if s == daemon_mod.CONNECT_RETRY_DELAY_S]
    assert len(retry_sleeps) == daemon_mod.CONNECT_RETRIES - 1


def test_restart_handles_missing_systemctl(tmp_path, recorder):
    """FileNotFoundError/TimeoutExpired from run() fall back gracefully."""

    def raising_run(args, **kwargs):
        if args[0] == "systemctl":
            raise FileNotFoundError("systemctl")
        raise subprocess.TimeoutExpired(args, 1)

    svc = make_service(tmp_path, recorder, runner=raising_run)
    assert svc.restart() is True
    assert recorder.popen == [["openrazer-daemon"]]
