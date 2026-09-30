# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the lighting claim registry (hueberry.backend.lighting_state)."""

import logging
import threading

from hueberry.backend import device_effects_store, lighting_state
from hueberry.backend.devices import ZoneInfo
from hueberry.ui import lighting_jobs

KBD = "KBD0001"
MOUSE = "MOUSE0001"
PAD = "PAD0001"
MATRIX_CAPS = ("lighting", "lighting_static", "lighting_led_matrix")
APPLIED = "applied"
THREAD_COUNT = 8


def test_claim_calls_every_listener_in_order():
    state = lighting_state.LightingState()
    first, second = [], []
    state.add_claim_listener(first.append)
    state.add_claim_listener(second.append)
    state.claim([KBD])
    state.claim(serial for serial in (PAD, MOUSE))
    assert first == [(KBD,), (PAD, MOUSE)]
    assert second == first


def test_claim_without_listeners_is_a_no_op():
    lighting_state.LightingState().claim([KBD])


def test_raising_listener_is_logged_and_others_still_run(caplog):
    state = lighting_state.LightingState()

    def boom(_serials):
        raise RuntimeError("listener broke")

    later = []
    state.add_claim_listener(boom)
    state.add_claim_listener(later.append)
    with caplog.at_level(logging.ERROR, logger=lighting_state.__name__):
        state.claim([KBD, PAD])
    assert "claim listener failed" in caplog.text
    assert f"{KBD}, {PAD}" in caplog.text
    assert later == [(KBD, PAD)]


def test_listeners_are_called_outside_the_lock():
    state = lighting_state.LightingState()
    added = []

    def reentrant(serials):
        state.add_claim_listener(added.append)  # would deadlock under the lock

    state.add_claim_listener(reentrant)
    state.claim([KBD])
    state.claim([PAD])
    assert (PAD,) in added


def test_claims_from_many_threads():
    state = lighting_state.LightingState()
    seen = []
    state.add_claim_listener(seen.append)
    threads = [threading.Thread(target=state.claim, args=([f"DEV{i}"],))
               for i in range(THREAD_COUNT)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(seen) == sorted((f"DEV{i}",) for i in range(THREAD_COUNT))


def test_shared_lighting_state_is_a_singleton():
    assert lighting_state.shared_lighting_state() is lighting_state.shared_lighting_state()


def test_claim_then_apply_claims_before_applying(monkeypatch, make_device):
    state = lighting_state.LightingState()
    order = []
    state.add_claim_listener(lambda serials: order.append(("claim", serials)))
    monkeypatch.setattr(lighting_state, "shared_lighting_state", lambda: state)

    def apply(*args):
        order.append(("apply", args[2]))
        return APPLIED

    dev = make_device(serial=KBD, capabilities=MATRIX_CAPS)
    assert lighting_jobs.claim_then_apply(dev, None, "static", {}, apply=apply) == APPLIED
    assert order == [("claim", (KBD,)), ("apply", "static")]


def test_claim_failure_never_blocks_apply(monkeypatch, make_device, caplog):
    def broken():
        raise RuntimeError("no state")

    monkeypatch.setattr(lighting_state, "shared_lighting_state", broken)
    dev = make_device(serial=KBD, capabilities=MATRIX_CAPS)
    with caplog.at_level(logging.ERROR, logger=lighting_jobs.__name__):
        result = lighting_jobs.claim_then_apply(dev, None, "static", {},
                                                apply=lambda *args: APPLIED)
    assert result == APPLIED
    assert KBD in caplog.text


RED = (255, 0, 0)
MAIN = ZoneInfo("main", "Main", "lighting", None)


def test_successful_apply_is_recorded(make_device):
    dev = make_device(serial=KBD, capabilities=MATRIX_CAPS)
    params = {"colour1": RED}
    assert lighting_jobs.claim_then_apply(dev, MAIN, "static", params,
                                          apply=lambda *args: True) is True
    assert device_effects_store.load_record(KBD, "main") == ("static", {"colour1": [255, 0, 0]})


def test_failed_apply_is_not_recorded(make_device):
    dev = make_device(serial=KBD, capabilities=MATRIX_CAPS)

    def broken(*_args):
        raise RuntimeError("apply broke")

    try:
        lighting_jobs.claim_then_apply(dev, MAIN, "static", {"colour1": RED}, apply=broken)
    except RuntimeError:
        pass
    lighting_jobs.claim_then_apply(dev, MAIN, "static", {"colour1": RED},
                                   apply=lambda *args: False)
    assert device_effects_store.load_record(KBD, "main") is None
    assert not device_effects_store.config_path().exists()


def test_record_failure_never_fails_apply(monkeypatch, make_device, caplog):
    def broken(*_args):
        raise OSError("disk full")

    monkeypatch.setattr(device_effects_store, "save_record", broken)
    dev = make_device(serial=KBD, capabilities=MATRIX_CAPS)
    with caplog.at_level(logging.ERROR, logger=lighting_jobs.__name__):
        result = lighting_jobs.claim_then_apply(dev, MAIN, "static", {"colour1": RED},
                                                apply=lambda *args: APPLIED)
    assert result == APPLIED
    assert "Could not record" in caplog.text
