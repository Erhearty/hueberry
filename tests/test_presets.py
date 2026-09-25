# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the pure Erheart preset maths."""

from pathlib import Path

import pytest

from hueberry.backend import presets

PRESETS_FILE = Path(presets.__file__)
PURPLE = (0xC0, 0x76, 0xFF)
MAUVE = (0xB8, 0x6C, 0xEA)
PINK = (0xFF, 0x3A, 0x82)
ROWS = 6
COLS = 22


def test_palette_parsed_from_hex():
    assert presets.PALETTE == (PURPLE, MAUVE, PINK, MAUVE, PURPLE)


@pytest.mark.parametrize(("pos", "expected"), [
    (0.0, PURPLE), (0.19, PURPLE), (0.2, MAUVE), (0.5, PINK), (0.99, PURPLE),
    (1.0, PURPLE), (1.5, PINK), (-0.5, PINK),
])
def test_palette_colour_is_stepwise(pos, expected):
    assert presets.palette_colour_at(pos) == expected


def test_wave_brightness_peaks_at_crest_and_wraps():
    assert presets.wave_brightness(0, 0, ROWS, COLS, 0.0) == 1.0
    assert presets.wave_brightness(ROWS - 1, COLS - 1, ROWS, COLS, 1.0) == 1.0
    assert presets.wave_brightness(0, 0, ROWS, COLS, 0.5) == pytest.approx(0.25)
    # distance wraps: 0.9 is 0.1 away from 0.0
    assert presets.wave_brightness(0, 0, ROWS, COLS, 0.9) == pytest.approx(0.81)


def test_wave_brightness_single_row_or_column():
    assert presets.wave_brightness(0, 0, 1, 1, 0.0) == 1.0


def test_matrix_colour_scales_palette_by_brightness():
    offset = 0.3
    row, col = 2, 7
    pos = (row / (ROWS - 1) + col / (COLS - 1)) / 2
    base = presets.palette_colour_at((pos + offset) % 1)
    bri = presets.wave_brightness(row, col, ROWS, COLS, offset)
    expected = tuple(int(channel * bri * presets.BRIGHTNESS) for channel in base)
    assert presets.matrix_colour(row, col, ROWS, COLS, offset) == expected


def test_zone_colour():
    assert presets.zone_colour(0.0) == PURPLE  # the corner (pos 1.0) wraps onto the crest
    offset = 0.5
    bri = presets.wave_brightness(1, 1, 2, 2, offset)
    expected = tuple(int(channel * bri) for channel in PINK)
    assert presets.zone_colour(offset) == expected


def test_next_offset_advances_and_wraps():
    assert presets.next_offset(0.0) == pytest.approx(presets.WAVE_SPEED)
    assert 0.0 <= presets.next_offset(0.9999) < 1.0


def test_serial_override():
    assert presets.SERIAL_OVERRIDES == {"ST2433V02000015": (255, 58, 130)}


@pytest.mark.parametrize("text", [
    "org.freedesktop.DBus.Error.UnknownMethod: nope",
    "org.freedesktop.DBus.Error.UnknownObject",
    "org.freedesktop.DBus.Error.ServiceUnknown",
    "org.freedesktop.DBus.Error.NoReply",
])
def test_stale_errors(text):
    assert presets.is_stale_error(RuntimeError(text))
    assert not presets.is_not_ready_error(RuntimeError(text))


@pytest.mark.parametrize("exc", [
    PermissionError("denied"), FileNotFoundError("missing"),
    RuntimeError("[Errno 13] Permission denied"), RuntimeError("[Errno 2] No such file"),
])
def test_not_ready_errors(exc):
    assert presets.is_not_ready_error(exc)
    assert not presets.is_stale_error(exc)


def test_other_errors_are_neither():
    exc = ValueError("bad value")
    assert not presets.is_stale_error(exc)
    assert not presets.is_not_ready_error(exc)


def test_presets_is_pure():
    text = PRESETS_FILE.read_text(encoding="utf-8")
    for forbidden in ("openrazer", "PyQt6"):
        assert f"import {forbidden}" not in text
        assert f"from {forbidden}" not in text
