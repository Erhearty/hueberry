# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for hueberry.backend.mouse against the fake openrazer device."""

import pytest

from hueberry.backend.mouse import FALLBACK_POLL_RATES, MIN_DPI, MouseControls, MouseError


def _mouse(make_device, *capabilities):
    dev = make_device(capabilities=("dpi", "poll_rate") + capabilities)
    return dev, MouseControls(dev)


def test_dpi_read(make_device):
    dev, mouse = _mouse(make_device)
    assert mouse.supports_dpi()
    assert mouse.max_dpi() == 16000
    assert mouse.get_dpi() == (800, 800)


def test_dpi_y_defaults_to_x_and_clamped(make_device):
    dev, mouse = _mouse(make_device)
    assert mouse.set_dpi(1600) == (1600, 1600)
    assert dev.dpi == (1600, 1600)
    assert mouse.set_dpi(50, 99999) == (MIN_DPI, 16000)
    assert dev.dpi == (MIN_DPI, 16000)


def test_dpi_snapped_to_available(make_device):
    dev, mouse = _mouse(make_device, "available_dpi")
    dev.available_dpi = [400, 800, 1600, 3200]
    assert mouse.set_dpi(1100) == (800, 0)
    assert mouse.set_dpi(2500) == (3200, 0)
    assert dev.dpi == (3200, 0)


def test_dpi_error_wrapped(make_device):
    dev, mouse = _mouse(make_device)
    del dev.max_dpi
    with pytest.raises(MouseError):
        mouse.set_dpi(800)


def test_poll_rate_supported_list(make_device):
    dev, mouse = _mouse(make_device, "supported_poll_rates")
    dev.supported_poll_rates = [125, 500, 1000, 4000]
    assert mouse.supports_poll_rate()
    assert mouse.supported_poll_rates() == [125, 500, 1000, 4000]
    assert mouse.set_poll_rate(4000) == 4000
    assert mouse.get_poll_rate() == 4000


def test_poll_rate_outside_list_rejected(make_device):
    dev, mouse = _mouse(make_device, "supported_poll_rates")
    with pytest.raises(ValueError):
        mouse.set_poll_rate(250)
    assert dev.poll_rate == 1000


def test_poll_rate_fallback_list(make_device):
    dev, mouse = _mouse(make_device)
    dev.supported_poll_rates = [8000]
    assert mouse.supported_poll_rates() == list(FALLBACK_POLL_RATES)
    with pytest.raises(ValueError):
        mouse.set_poll_rate(8000)


def test_not_a_mouse(make_device):
    dev = make_device(capabilities=())
    mouse = MouseControls(dev)
    assert not mouse.supports_dpi()
    assert not mouse.supports_poll_rate()
