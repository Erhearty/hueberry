# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for hueberry.backend.devices."""

from hueberry.backend.devices import UNKNOWN, describe_device, list_zones


def test_describe_device_reads_fields(make_device):
    """All fields are copied and capabilities mapped."""
    dev = make_device(name="Razer DeathAdder", serial="S1",
                      capabilities=("dpi", "lighting_led_matrix"))
    info = describe_device(dev)
    assert info.name == "Razer DeathAdder"
    assert info.type == "mouse"
    assert info.serial == "S1"
    assert info.firmware_version == "v1.0"
    assert info.driver_version == "3.12.1"
    assert info.has_matrix is True
    assert info.is_mouse is True


def test_describe_device_non_mouse(make_device):
    """Devices without dpi are not mice and have no matrix by default."""
    info = describe_device(make_device(device_type="keyboard"))
    assert info.is_mouse is False
    assert info.has_matrix is False


class _BrokenDevice:
    """Device whose every attribute read and capability query raises."""

    def __getattr__(self, name):
        raise RuntimeError(f"D-Bus error reading {name}")


def test_attribute_errors_become_unknown():
    """D-Bus/attribute errors turn into 'Unknown' / False."""
    info = describe_device(_BrokenDevice())
    assert info.name == UNKNOWN
    assert info.type == UNKNOWN
    assert info.serial == UNKNOWN
    assert info.firmware_version == UNKNOWN
    assert info.driver_version == UNKNOWN
    assert info.has_matrix is False
    assert info.is_mouse is False
    assert list_zones(_BrokenDevice()) == []


def test_list_zones_main_and_misc(make_device):
    """Main zone plus non-None misc zones, scroll_wheel mapped to 'scroll'."""
    dev = make_device(capabilities=("lighting",), zones=("logo", "scroll_wheel"))
    zones = list_zones(dev)
    assert [z.key for z in zones] == ["main", "logo", "scroll_wheel"]
    main, logo, scroll = zones
    assert main.obj is dev.fx
    assert main.capability_prefix == "lighting"
    assert logo.capability_prefix == "lighting_logo"
    assert logo.obj is dev.fx.misc.logo
    assert scroll.capability_prefix == "lighting_scroll"
    assert scroll.label == "Scroll wheel"


def test_list_zones_without_main_lighting(make_device):
    """No 'lighting' capability means no main zone; all misc zones listed."""
    all_zones = ("logo", "scroll_wheel", "left", "right", "backlight",
                 "charging", "fast_charging", "fully_charged")
    zones = list_zones(make_device(zones=all_zones))
    assert [z.key for z in zones] == list(all_zones)
    assert zones[-1].capability_prefix == "lighting_fully_charged"
