# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for reapplying the recorded lighting after a start."""

import pytest

from hueberry.backend import device_effects_store
from hueberry.ui import main_window, startup_lighting
from hueberry.ui.main_window import MainWindow

SERIAL = "KBD0001"
CAPS = ("lighting", "lighting_static", "lighting_spectrum", "lighting_logo_static")
RED = (255, 0, 0)


@pytest.fixture(autouse=True)
def _fresh():
    startup_lighting.reset()
    yield
    startup_lighting.reset()


@pytest.fixture
def device(make_device):
    return make_device(serial=SERIAL, capabilities=CAPS, zones=("logo",))


def test_recorded_effect_applied_with_params(device):
    device_effects_store.save_record(SERIAL, "main", "static", {"colour1": RED})
    before = device_effects_store.config_path().read_bytes()
    startup_lighting.reapply_recorded([device])
    assert device.fx.calls == [("static", RED)]
    assert device.fx.misc.logo.calls == []  # no record: untouched
    assert device_effects_store.config_path().read_bytes() == before


def test_reapplied_once_per_serial(device):
    startup_lighting.reapply_recorded([device])  # no records yet: still done
    device_effects_store.save_record(SERIAL, "main", "spectrum", {})
    startup_lighting.reapply_recorded([device])
    assert device.fx.calls == []
    startup_lighting.reset()
    startup_lighting.reapply_recorded([device])
    startup_lighting.reapply_recorded([device])
    assert device.fx.calls == [("spectrum", ())]


class _Window:
    """Stands in for MainWindow's ``self`` in ``_refresh_animations``."""

    def __init__(self):
        self.statuses = []

    def show_status(self, text):
        self.statuses.append(text)


def test_refresh_reapplies_records_before_restoring_last(device, monkeypatch):
    device_effects_store.save_record(SERIAL, "main", "static", {"colour1": RED})
    seen = []
    monkeypatch.setattr(main_window.effects_wiring, "restore_last",
                        lambda devices: seen.append(list(device.fx.calls)))
    win = _Window()
    MainWindow._refresh_animations(win, [device])
    assert seen == [[("static", RED)]]  # the record was applied first
    assert win.statuses == []


def test_refresh_restores_last_when_reapply_fails(device, monkeypatch):
    def boom(devices):
        raise RuntimeError("reapply broke")

    restored = []
    monkeypatch.setattr(main_window.startup_lighting, "reapply_recorded", boom)
    monkeypatch.setattr(main_window.effects_wiring, "restore_last", restored.append)
    win = _Window()
    MainWindow._refresh_animations(win, [device])
    assert restored == [[device]]
    assert win.statuses == ["Animation error: reapply broke"]


def test_error_is_logged_not_raised(device, caplog):
    device_effects_store.save_record(SERIAL, "main", "spectrum", {})
    device_effects_store.save_record(SERIAL, "logo", "static", {"colour1": RED})

    def boom():
        raise RuntimeError("dbus down")

    device.fx.spectrum = boom
    startup_lighting.reapply_recorded([device])
    assert "Reapplying spectrum on KBD0001/main failed" in caplog.text
    assert device.fx.misc.logo.calls == [("static", RED)]
