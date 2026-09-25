# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for MacroEngineService with fake processes and a fake client."""

import subprocess

import pytest

from hueberry.backend import macro_engine
from hueberry.backend.macro_engine import MacroEngineService
from hueberry.macro_engine import main as engine_main
from hueberry.macros.protocol import EngineError, EngineUnavailable

PARENT_PID = 4242
PYTHON = "/usr/bin/python3"


class FakeProcess:
    """Popen stand-in: ``codes`` are returned by successive poll() calls."""

    def __init__(self, codes=(), hang=False):
        self.codes = list(codes)
        self.hang = hang
        self.pid = 999
        self.calls = []

    def poll(self):
        if self.codes:
            return self.codes.pop(0)
        return None if "terminate" not in self.calls else 0

    def terminate(self):
        self.calls.append("terminate")

    def kill(self):
        self.calls.append("kill")

    def wait(self, timeout=None):
        self.calls.append(("wait", timeout))
        if self.hang and timeout is not None:
            raise subprocess.TimeoutExpired("engine", timeout)
        return 0


class FakePopen:
    def __init__(self, process=None, error=None):
        self.process = process or FakeProcess()
        self.error = error
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.error is not None:
            raise self.error
        return self.process


class FakeClient:
    """``answers`` is consumed per request: an exception is raised, a dict returned."""

    def __init__(self, answers=()):
        self.answers = list(answers)
        self.requests = []

    def request(self, op, **args):
        self.requests.append((op, args))
        answer = self.answers.pop(0) if self.answers else {}
        if isinstance(answer, Exception):
            raise answer
        return answer


def _service(popen=None, client=None):
    sleeps = []
    service = MacroEngineService(popen=popen or FakePopen(), sleep=sleeps.append,
                                 client=client or FakeClient(), python=PYTHON,
                                 parent_pid=PARENT_PID)
    return service, sleeps


def test_exit_codes_match_engine():
    assert macro_engine.EXIT_OK == engine_main.EXIT_OK
    assert macro_engine.EXIT_ERROR == engine_main.EXIT_ERROR
    assert macro_engine.EXIT_ALREADY_RUNNING == engine_main.EXIT_ALREADY_RUNNING
    assert macro_engine.EXIT_NO_EVDEV == engine_main.EXIT_NO_EVDEV


def test_spawn_argv_and_readiness_wait():
    popen = FakePopen()
    client = FakeClient([EngineUnavailable("not yet"), EngineUnavailable("not yet"), {"pong": True}])
    service, sleeps = _service(popen, client)
    assert service.start()
    ((argv, kwargs),) = popen.calls
    assert argv == [PYTHON, "-m", "hueberry.macro_engine", "--parent-pid", str(PARENT_PID)]
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert sleeps == [macro_engine.READY_POLL_S] * 2
    assert [op for op, _args in client.requests] == ["ping"] * 3
    assert service.state == macro_engine.STATE_RUNNING
    assert not service.adopted


def test_spawn_does_not_wait_and_wait_ready_pings():
    popen = FakePopen()
    client = FakeClient([EngineUnavailable("not yet"), {"pong": True}])
    service, sleeps = _service(popen, client)
    assert service.spawn()
    assert len(popen.calls) == 1
    assert client.requests == [] and sleeps == []
    assert service.state == macro_engine.STATE_STARTING
    assert service.wait_ready()
    assert service.state == macro_engine.STATE_RUNNING


def test_wait_ready_after_failed_spawn_does_not_ping():
    client = FakeClient()
    service, _sleeps = _service(FakePopen(error=OSError("no python")), client)
    assert not service.spawn()
    assert not service.wait_ready()
    assert client.requests == []


def test_start_twice_does_not_respawn():
    popen = FakePopen()
    service, _sleeps = _service(popen)
    assert service.start()
    assert service.start()
    assert len(popen.calls) == 1


def test_adopts_already_running_engine():
    popen = FakePopen(FakeProcess(codes=[macro_engine.EXIT_ALREADY_RUNNING]))
    service, _sleeps = _service(popen, FakeClient([{"pong": True}]))
    assert service.start()
    assert service.adopted
    assert service.state == macro_engine.STATE_RUNNING
    service.stop()  # an adopted engine is not ours to terminate
    assert popen.process.calls == []


def test_evdev_missing():
    popen = FakePopen(FakeProcess(codes=[macro_engine.EXIT_NO_EVDEV]))
    service, _sleeps = _service(popen)
    assert not service.start()
    assert service.state == macro_engine.STATE_EVDEV_MISSING
    assert "evdev" in service.last_error


def test_crash_during_startup():
    popen = FakePopen(FakeProcess(codes=[macro_engine.EXIT_ERROR]))
    service, _sleeps = _service(popen)
    assert not service.start()
    assert service.state == macro_engine.STATE_CRASHED
    assert "code 1" in service.last_error


def test_spawn_failure():
    service, _sleeps = _service(FakePopen(error=OSError("no python")))
    assert not service.start()
    assert service.state == macro_engine.STATE_CRASHED
    assert "no python" in service.last_error


def test_readiness_timeout():
    answers = [EngineUnavailable("down")] * macro_engine.READY_ATTEMPTS
    service, sleeps = _service(client=FakeClient(answers))
    assert not service.start()
    assert service.state == macro_engine.STATE_UNAVAILABLE
    assert len(sleeps) == macro_engine.READY_ATTEMPTS


def test_stop_terminates_and_waits():
    popen = FakePopen()
    service, _sleeps = _service(popen)
    service.start()
    service.stop()
    assert popen.process.calls == ["terminate", ("wait", macro_engine.STOP_TIMEOUT_S)]
    assert service.state == macro_engine.STATE_STOPPED


def test_stop_kills_after_timeout():
    popen = FakePopen(FakeProcess(hang=True))
    service, _sleeps = _service(popen)
    service.start()
    service.stop()
    assert popen.process.calls == ["terminate", ("wait", macro_engine.STOP_TIMEOUT_S), "kill",
                                   ("wait", None)]


def test_poll_detects_crash():
    process = FakeProcess()
    service, _sleeps = _service(FakePopen(process))
    service.start()
    process.codes = [macro_engine.EXIT_ERROR]
    assert service.poll() == macro_engine.STATE_CRASHED
    assert "code 1" in service.last_error


def test_unavailable_maps_state():
    client = FakeClient([{"pong": True}, EngineUnavailable("gone")])
    service, _sleeps = _service(client=client)
    service.start()
    with pytest.raises(EngineUnavailable):
        service.status()
    assert service.state == macro_engine.STATE_UNAVAILABLE
    assert "gone" in service.last_error


def test_engine_error_keeps_running_state():
    client = FakeClient([{"pong": True}, EngineError("not recording")])
    service, _sleeps = _service(client=client)
    service.start()
    with pytest.raises(EngineError):
        service.record_stop()
    assert service.state == macro_engine.STATE_RUNNING


def test_client_calls():
    client = FakeClient([{"devices": []}, {"devices": [], "permissions": {}}, {}, {}, {}])
    service, _sleeps = _service(client=client)
    assert service.status() == {"devices": []}
    assert service.list_devices()["permissions"] == {}
    service.reload()
    service.record_start("dev-1")
    service.record_stop()
    assert client.requests == [("status", {}), ("list_devices", {}), ("reload", {}),
                               ("record_start", {"identity": "dev-1"}), ("record_stop", {})]
