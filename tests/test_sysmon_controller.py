# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for hueberry.sysmon.controller (no real processes, sleeps or files outside tmp)."""

import signal
import subprocess
from dataclasses import replace
from types import SimpleNamespace

import pytest

from hueberry.sysmon import controller as ctl_mod
from hueberry.sysmon.config import SysmonConfig
from hueberry.sysmon.controller import SysmonController, default_pid_path, read_cmdline

FIRST_PID = 4000
STALE_PID = 999


class FakeProc:
    """Minimal Popen stand-in; ``returncode`` None means still running."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.returncode = None
        self.waits: list[float] = []

    def poll(self):
        """Current exit status (None while alive)."""
        return self.returncode

    def wait(self, timeout=None):
        """Record the reap attempt."""
        self.waits.append(timeout)
        return self.returncode


@pytest.fixture
def rec(tmp_path):
    """Recorder for every injected side effect; ``dies_on`` picks which signals kill."""
    r = SimpleNamespace(popen=[], procs=[], kills=[], sleeps=[], saves=[], writes=[],
                        alive=set(), dies_on={signal.SIGTERM, signal.SIGKILL},
                        cmdlines={}, emitted=[], stored=SysmonConfig(enabled=False),
                        waybar="/usr/bin/waybar", popen_error=None, save_error=None)
    r.out_dir = tmp_path / "out"
    r.pid_path = tmp_path / "run" / "hueberry" / "sysmon.pid"
    r.config_path = tmp_path / "sysmon.json"

    def popen(args, **kwargs):
        if r.popen_error:
            raise r.popen_error
        proc = FakeProc(FIRST_PID + len(r.procs))
        r.popen.append((args, kwargs))
        r.procs.append(proc)
        r.alive.add(proc.pid)
        return proc

    def killpg(pid, sig):
        r.kills.append((pid, sig))
        if pid not in r.alive:
            raise ProcessLookupError(pid)
        if sig in r.dies_on:
            r.alive.discard(pid)
            for proc in r.procs:
                if proc.pid == pid:
                    proc.returncode = -sig

    def save(cfg, path):
        if r.save_error:
            raise r.save_error
        r.saves.append((cfg, path))

    def write_files(cfg, config_path, out_dir):
        r.writes.append((cfg, config_path, out_dir))
        return out_dir / "config.json", out_dir / "style.css"

    r.popen_fn, r.killpg_fn, r.save_fn, r.write_fn = popen, killpg, save, write_files
    return r


def make(rec):
    """Controller wired to the recorder; state_changed collected in ``rec.emitted``."""
    ctl = SysmonController(
        popen=rec.popen_fn, which=lambda name: rec.waybar, killpg=rec.killpg_fn,
        is_alive=lambda pid: pid in rec.alive, sleep=rec.sleeps.append,
        read_cmdline=lambda pid: rec.cmdlines.get(pid, []), pid_path=rec.pid_path,
        config_path=rec.config_path, out_dir=rec.out_dir, load=lambda path: rec.stored,
        save=rec.save_fn, write_files=rec.write_fn,
    )
    ctl.state_changed.connect(rec.emitted.append)
    return ctl


def test_start_spawns_waybar(rec):
    """start() writes files, spawns waybar detached, records the pid, persists and emits."""
    ctl = make(rec)
    assert ctl.start() is True
    args, kwargs = rec.popen[0]
    assert args == ["waybar", "-c", str(rec.out_dir / "config.json"),
                    "-s", str(rec.out_dir / "style.css")]
    assert kwargs == {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                      "stderr": subprocess.DEVNULL, "start_new_session": True}
    assert rec.writes == [(rec.stored, rec.config_path, rec.out_dir)]
    assert rec.pid_path.read_text() == f"{FIRST_PID}\n"
    assert [(cfg.enabled, path) for cfg, path in rec.saves] == [(True, rec.config_path)]
    assert ctl.config.enabled is True
    assert rec.emitted == [True]
    assert ctl.is_running() is True


def test_start_when_running_is_noop(rec):
    """A second start() spawns nothing and emits nothing."""
    ctl = make(rec)
    ctl.start()
    assert ctl.start() is True
    assert len(rec.popen) == 1 and rec.emitted == [True]


def test_start_without_waybar(rec):
    """Missing waybar: last_error set, nothing written or spawned."""
    rec.waybar = None
    ctl = make(rec)
    assert ctl.start() is False
    assert ctl.last_error == "waybar not found"
    assert rec.popen == [] and rec.writes == [] and rec.emitted == [] and rec.saves == []


def test_start_popen_failure(rec):
    """An OSError from Popen is reported through last_error, not raised."""
    rec.popen_error = OSError("exec format error")
    ctl = make(rec)
    assert ctl.start() is False
    assert "exec format error" in ctl.last_error
    assert rec.emitted == [] and rec.saves == []
    assert not rec.pid_path.exists()


def test_stop_sigterm_only(rec):
    """A process that dies on SIGTERM is not SIGKILLed; pid file removed; persisted off."""
    ctl = make(rec)
    ctl.start()
    ctl.stop()
    assert rec.kills == [(FIRST_PID, signal.SIGTERM)]
    assert rec.sleeps == []
    assert not rec.pid_path.exists()
    assert [cfg.enabled for cfg, _ in rec.saves] == [True, False]
    assert rec.emitted == [True, False]
    assert ctl.is_running() is False


def test_stop_escalates_to_sigkill(rec):
    """A process ignoring SIGTERM is polled for STOP_TIMEOUT_S, then SIGKILLed and reaped."""
    rec.dies_on = {signal.SIGKILL}
    ctl = make(rec)
    ctl.start()
    proc = rec.procs[0]
    ctl.stop()
    assert rec.kills == [(FIRST_PID, signal.SIGTERM), (FIRST_PID, signal.SIGKILL)]
    assert rec.sleeps == [ctl_mod.STOP_POLL_S] * ctl_mod.STOP_POLL_STEPS
    assert proc.poll() == -signal.SIGKILL
    assert rec.emitted == [True, False]


def test_stop_reaps_unfinished_child(rec):
    """A child still unreaped after the kill sequence is waited on with a timeout."""
    rec.dies_on = set()
    ctl = make(rec)
    ctl.start()
    proc = rec.procs[0]
    ctl.stop()
    assert proc.waits == [ctl_mod.REAP_TIMEOUT_S]


def test_stop_tolerates_vanished_process(rec):
    """ProcessLookupError from killpg is fine."""
    ctl = make(rec)
    ctl.start()
    rec.alive.clear()
    ctl.stop()
    assert rec.emitted == [True, False]
    assert not rec.pid_path.exists()


def test_toggle(rec):
    """toggle() starts, then stops."""
    ctl = make(rec)
    assert ctl.toggle() is True
    assert ctl.toggle() is False
    assert rec.emitted == [True, False]


def test_apply_returns_problems_without_changes(rec):
    """An invalid config is rejected: nothing saved, written or restarted."""
    ctl = make(rec)
    problems = ctl.apply(SysmonConfig(align_x="nowhere"))
    assert problems and "align_x" in problems[0]
    assert rec.saves == [] and rec.writes == []
    assert ctl.config == rec.stored


def test_apply_when_stopped_saves_and_rewrites(rec):
    """Stopped: saved (enabled kept), files rewritten, no process spawned."""
    ctl = make(rec)
    new_cfg = SysmonConfig(enabled=True, margin_top=12)
    assert ctl.apply(new_cfg) == []
    expected = replace(new_cfg, enabled=False)
    assert rec.saves == [(expected, rec.config_path)]
    assert rec.writes == [(expected, rec.config_path, rec.out_dir)]
    assert ctl.config == expected
    assert rec.popen == []


def test_apply_when_running_restarts(rec):
    """Running: the old waybar is stopped and a new one launched with the new files."""
    ctl = make(rec)
    ctl.start()
    assert ctl.apply(SysmonConfig(enabled=False, margin_top=12)) == []
    assert ctl.config.enabled is True and ctl.config.margin_top == 12
    assert rec.kills == [(FIRST_PID, signal.SIGTERM)]
    assert len(rec.popen) == 2
    assert rec.pid_path.read_text() == f"{FIRST_PID + 1}\n"
    assert rec.writes[-1][0] == ctl.config
    assert rec.emitted == [True]


def test_save_failure_sets_last_error(rec):
    """A failing save is reported via last_error; the overlay still starts."""
    rec.save_error = OSError("disk full")
    ctl = make(rec)
    assert ctl.start() is True
    assert "disk full" in ctl.last_error


def test_shutdown_preserves_enabled(rec):
    """shutdown() stops waybar but does not persist enabled=False."""
    ctl = make(rec)
    ctl.start()
    ctl.shutdown()
    assert [cfg.enabled for cfg, _ in rec.saves] == [True]
    assert ctl.config.enabled is True
    assert rec.kills == [(FIRST_PID, signal.SIGTERM)]
    assert not rec.pid_path.exists()
    assert rec.emitted == [True, False]


def test_restore(rec):
    """restore() starts only when the stored config is enabled."""
    assert make(rec).restore() is False
    assert rec.popen == []
    rec.stored = SysmonConfig(enabled=True)
    assert make(rec).restore() is True
    assert len(rec.popen) == 1
    assert rec.saves == []  # already enabled: nothing to persist


def test_stale_pid_of_our_waybar_is_killed(rec):
    """A stale pid whose cmdline is waybar with our config is terminated first."""
    rec.pid_path.parent.mkdir(parents=True)
    rec.pid_path.write_text(f"{STALE_PID}\n")
    rec.alive.add(STALE_PID)
    rec.cmdlines[STALE_PID] = ["/usr/bin/waybar", "-c", str(rec.out_dir / "config.json"),
                               "-s", str(rec.out_dir / "style.css")]
    make(rec).start()
    assert rec.kills == [(STALE_PID, signal.SIGTERM)]
    assert rec.pid_path.read_text() == f"{FIRST_PID}\n"


@pytest.mark.parametrize("cmdline", [
    ["/usr/bin/bash"],
    ["/usr/bin/waybar", "-c", "/home/user/.config/waybar/config"],
    ["/usr/bin/python3", "waybar", "config.json"],
    [],
])
def test_stale_pid_of_other_process_is_ignored(rec, cmdline):
    """A reused pid not running our waybar config is never signalled; the file is replaced."""
    rec.pid_path.parent.mkdir(parents=True)
    rec.pid_path.write_text(f"{STALE_PID}\n")
    rec.alive.add(STALE_PID)
    rec.cmdlines[STALE_PID] = cmdline
    make(rec).start()
    assert rec.kills == []
    assert STALE_PID in rec.alive
    assert rec.pid_path.read_text() == f"{FIRST_PID}\n"


def test_garbage_pid_file_is_removed(rec):
    """An unparsable pid file is simply replaced."""
    rec.pid_path.parent.mkdir(parents=True)
    rec.pid_path.write_text("garbage")
    make(rec).start()
    assert rec.kills == []
    assert rec.pid_path.read_text() == f"{FIRST_PID}\n"


def test_read_cmdline(tmp_path):
    """NUL-separated /proc cmdline is split; an unreadable one is []."""
    (tmp_path / "42").mkdir()
    (tmp_path / "42" / "cmdline").write_bytes(b"waybar\0-c\0/x/config.json\0")
    assert read_cmdline(42, proc_root=tmp_path) == ["waybar", "-c", "/x/config.json"]
    assert read_cmdline(43, proc_root=tmp_path) == []


def test_default_pid_path_uses_xdg_runtime_dir(tmp_path, monkeypatch):
    """The pid file lives in $XDG_RUNTIME_DIR/hueberry."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert default_pid_path() == tmp_path / "hueberry" / "sysmon.pid"
