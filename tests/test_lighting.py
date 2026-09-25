# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for hueberry.backend.lighting against the fake openrazer device."""

import pytest

from hueberry.backend import lighting
from hueberry.backend.devices import list_zones
from hueberry.backend.lighting import LightingError

RED = (255, 0, 0)
BLUE = (0, 0, 255)


def _zone(dev, key):
    return next(zone for zone in list_zones(dev) if zone.key == key)


def _keys(effects):
    return [effect.key for effect in effects]


def test_main_effects_filtered_by_capability(make_device):
    dev = make_device(capabilities=("lighting", "lighting_static", "lighting_wave"))
    assert _keys(lighting.supported_effects(dev, _zone(dev, "main"))) == ["static", "wave"]


def test_misc_effects_filtered_by_capability(make_device):
    dev = make_device(
        capabilities=("lighting_logo_static", "lighting_scroll_pulsate", "lighting_static"),
        zones=("logo", "scroll_wheel"))
    assert _keys(lighting.supported_effects(dev, _zone(dev, "logo"))) == ["static"]
    assert _keys(lighting.supported_effects(dev, _zone(dev, "scroll_wheel"))) == ["pulsate"]


def test_effects_filtered_by_method_existence(make_device):
    dev = make_device(
        capabilities=("lighting", "lighting_blinking", "lighting_logo_starlight_single",
                      "lighting_logo_blinking"),
        zones=("logo",))
    # FakeFx has no blinking(); FakeLed has no starlight_single().
    assert lighting.supported_effects(dev, _zone(dev, "main")) == []
    assert _keys(lighting.supported_effects(dev, _zone(dev, "logo"))) == ["blinking"]


@pytest.mark.parametrize("key, params, expected", [
    ("static", {"colour1": RED}, ("static", (255, 0, 0))),
    ("breath_dual", {"colour1": RED, "colour2": BLUE},
     ("breath_dual", (255, 0, 0, 0, 0, 255))),
    ("starlight_dual", {"colour1": RED, "colour2": BLUE, "time": lighting.REACTIVE_LONG},
     ("starlight_dual", (255, 0, 0, 0, 0, 255, 3))),
    ("reactive", {"colour1": BLUE, "time": lighting.REACTIVE_SHORT},
     ("reactive", (0, 0, 255, 1))),
    ("wave", {"direction": lighting.WAVE_LEFT}, ("wave", (2,))),
    ("spectrum", None, ("spectrum", ())),
])
def test_apply_effect_calls_method_with_args(make_device, key, params, expected):
    dev = make_device(capabilities=("lighting", f"lighting_{key}"))
    assert lighting.apply_effect(dev, _zone(dev, "main"), key, params) is True
    assert dev.fx.calls == [expected]


def test_apply_effect_on_misc_zone(make_device):
    dev = make_device(capabilities=("lighting_scroll_pulsate",), zones=("scroll_wheel",))
    zone = _zone(dev, "scroll_wheel")
    lighting.apply_effect(dev, zone, "pulsate", {"colour1": (1, 2, 3)})
    assert dev.fx.misc.scroll_wheel.calls == [("pulsate", (1, 2, 3))]


@pytest.mark.parametrize("colour", [(256, 0, 0), (-1, 0, 0), (1, 2), (1.0, 2, 3), "red"])
def test_invalid_colour_rejected(make_device, colour):
    dev = make_device(capabilities=("lighting", "lighting_static"))
    with pytest.raises(ValueError):
        lighting.apply_effect(dev, _zone(dev, "main"), "static", {"colour1": colour})
    assert dev.fx.calls == []


def test_invalid_time_and_direction_rejected(make_device):
    dev = make_device(capabilities=("lighting", "lighting_wave", "lighting_reactive"))
    zone = _zone(dev, "main")
    with pytest.raises(ValueError):
        lighting.apply_effect(dev, zone, "wave", {"direction": 5})
    with pytest.raises(ValueError):
        lighting.apply_effect(dev, zone, "reactive", {"colour1": RED, "time": 9})
    with pytest.raises(ValueError):
        lighting.apply_effect(dev, zone, "reactive", {"colour1": RED})


def test_unsupported_or_unknown_effect_rejected(make_device):
    dev = make_device(capabilities=("lighting",))
    zone = _zone(dev, "main")
    with pytest.raises(LightingError):
        lighting.apply_effect(dev, zone, "static", {"colour1": RED})
    with pytest.raises(ValueError):
        lighting.apply_effect(dev, zone, "disco", {})
    assert dev.fx.calls == []


def test_dbus_exception_wrapped(make_device, monkeypatch):
    dev = make_device(capabilities=("lighting", "lighting_spectrum"))

    def boom():
        raise RuntimeError("org.freedesktop.DBus.Error.NoReply")

    monkeypatch.setattr(dev.fx, "spectrum", boom)
    with pytest.raises(LightingError):
        lighting.apply_effect(dev, _zone(dev, "main"), "spectrum")


def test_brightness_main_clamped(make_device):
    dev = make_device(capabilities=("lighting", "brightness"))
    zone = _zone(dev, "main")
    assert lighting.supports_brightness(dev, zone)
    assert lighting.set_brightness(dev, zone, 150) == lighting.BRIGHTNESS_MAX
    assert dev.brightness == 100.0
    assert lighting.set_brightness(dev, zone, -5) == lighting.BRIGHTNESS_MIN
    assert lighting.get_brightness(dev, zone) == 0.0


def test_brightness_misc_clamped(make_device):
    dev = make_device(capabilities=("lighting_logo_brightness",), zones=("logo",))
    zone = _zone(dev, "logo")
    assert lighting.supports_brightness(dev, zone)
    assert lighting.set_brightness(dev, zone, 250) == 100.0
    assert dev.fx.misc.logo.brightness == 100.0
    lighting.set_brightness(dev, zone, 42)
    assert lighting.get_brightness(dev, zone) == 42.0
    assert dev.brightness == 100.0


def test_brightness_unsupported_and_error(make_device):
    dev = make_device(capabilities=("lighting",), zones=("logo",))
    assert not lighting.supports_brightness(dev, _zone(dev, "main"))
    assert not lighting.supports_brightness(dev, _zone(dev, "logo"))
    del dev.brightness
    with pytest.raises(LightingError):
        lighting.get_brightness(dev, _zone(dev, "main"))
