# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for turning every lighting zone off on shutdown."""

from hueberry.backend import device_effects_store, lights_off
from hueberry.backend.lights_off import OFF_COLOUR

NONE_CAPS = ("lighting", "lighting_none", "lighting_logo_none")
STATIC_CAPS = ("lighting", "lighting_static")


def test_main_and_misc_zones_get_none(make_device):
    dev = make_device(capabilities=NONE_CAPS, zones=("logo",))
    assert lights_off.turn_off([dev]) == 2
    assert dev.fx.calls == [("none", ())]
    assert dev.fx.misc.logo.calls == [("none", ())]


def test_static_black_when_none_unsupported(make_device):
    dev = make_device(capabilities=STATIC_CAPS)
    assert lights_off.turn_off([dev]) == 1
    assert dev.fx.calls == [("static", OFF_COLOUR)]


def test_failing_zone_does_not_stop_others(make_device, caplog):
    broken = make_device(serial="BROKEN", capabilities=NONE_CAPS, zones=("logo",))

    def boom():
        raise RuntimeError("dbus down")

    broken.fx.none = boom
    other = make_device(serial="OTHER", capabilities=STATIC_CAPS)
    assert lights_off.turn_off([broken, other]) == 2
    assert broken.fx.misc.logo.calls == [("none", ())]
    assert other.fx.calls == [("static", OFF_COLOUR)]
    assert "Turning off zone main failed" in caplog.text


def test_device_effects_file_untouched(make_device, monkeypatch):
    path = device_effects_store.config_path()
    saves = []
    monkeypatch.setattr(device_effects_store, "save_record", lambda *a, **k: saves.append(a))
    lights_off.turn_off([make_device(capabilities=NONE_CAPS, zones=("logo",))])
    assert saves == []
    assert not path.exists()
