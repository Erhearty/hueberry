# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for turning the lighting off on every shutdown path."""

import os
import signal

import pytest

from fake_app import FakeSignal
from hueberry import shutdown_lighting
from hueberry.shutdown_lighting import QUIT_SIGNALS, ShutdownLighting

NO_WAKEUP_FD = -1  # signal.set_wakeup_fd's "disabled" value


class _Service:
    """Stands in for DaemonService."""

    def __init__(self, connected=True):
        self.connected = connected
        self.devices = ["device"]


class _Runtime:
    """Stands in for the per-key runtime; records shutdown calls in ``order``."""

    def __init__(self, order):
        self.order = order

    def shutdown(self, **kwargs):
        self.order.append(("shutdown", kwargs))


class _App:
    """Stands in for QApplication: quit/logout signals and a quit counter."""

    def __init__(self, session=True):
        self.aboutToQuit = FakeSignal()
        if session:
            self.commitDataRequest = FakeSignal()
        self.quit_calls = 0

    def quit(self):
        self.quit_calls += 1


@pytest.fixture
def order(monkeypatch):
    calls = []
    monkeypatch.setattr(shutdown_lighting.lights_off, "turn_off",
                        lambda devices: calls.append(("off", list(devices))))
    return calls


def _lighting(order, connected=True):
    return ShutdownLighting(_Service(connected), runtime_getter=lambda: _Runtime(order))


def test_run_stops_runtime_then_turns_off_once(order):
    lighting = _lighting(order)
    lighting.run()
    lighting.run()
    assert order == [("shutdown", {"restore": False}), ("off", ["device"])]


def test_run_skips_turn_off_when_disconnected(order):
    _lighting(order, connected=False).run()
    assert order == [("shutdown", {"restore": False})]


def test_failing_runtime_still_turns_off(order, caplog):
    def broken():
        raise RuntimeError("runtime broke")

    ShutdownLighting(_Service(), runtime_getter=broken).run()
    assert order == [("off", ["device"])]
    assert "Stopping the per-key runtime on shutdown failed" in caplog.text


def test_install_does_not_bind_commit_data_request(order):
    app = _App()
    lighting = _lighting(order)
    lighting.install(app)
    try:
        assert app.commitDataRequest.slots == []  # a logout can still be cancelled
        assert app.aboutToQuit.slots == [lighting.run]
    finally:
        lighting.uninstall()


def test_install_tolerates_app_without_signals(order):
    lighting = _lighting(order)
    lighting.install(object())
    lighting.uninstall()
    assert order == []


def test_sigterm_quits_the_app(order, qapp):
    app = _App(session=False)
    lighting = _lighting(order)
    lighting.install(app)
    try:
        os.kill(os.getpid(), signal.SIGTERM)
        qapp.processEvents()
        assert app.quit_calls == 1
        with pytest.raises(BlockingIOError):
            lighting._sockets[0].recv(1)  # the wakeup bytes were drained
    finally:
        lighting.uninstall()


def test_uninstall_restores_handlers_and_wakeup_fd(order, qapp):
    before = {signum: signal.getsignal(signum) for signum in QUIT_SIGNALS}
    previous_fd = signal.set_wakeup_fd(NO_WAKEUP_FD)
    signal.set_wakeup_fd(previous_fd)
    lighting = _lighting(order)
    lighting.install(_App())
    try:
        assert all(signal.getsignal(s) is not before[s] for s in QUIT_SIGNALS)
    finally:
        lighting.uninstall()
    assert {signum: signal.getsignal(signum) for signum in QUIT_SIGNALS} == before
    assert signal.set_wakeup_fd(previous_fd) == previous_fd
