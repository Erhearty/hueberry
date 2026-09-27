# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for matching devices to device-map SVGs (hand-made fixture maps)."""

from pathlib import Path

import pytest

from hueberry.backend import device_maps
from hueberry.backend.device_maps import DeviceMap

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "devicemaps"
ROWS = 2
COLS = 3
KEYBOARD = "Test Keyboard"
BOARD = "Test Board"
US_SVG = "kbd_en_US.xml"
GB_SVG = "kbd_en_GB.xml"
GADGET = "Test Gadget"
TEST_ALIASES = {"test gadget": "test board", "test keyboard": "test board"}
V4 = "Razer BlackWidow V4"
V4_ROWS = 8
V4_COLS = 23
V4_PRO_SVG = "blackwidow_v4_pro_en_US.svg"
OTHER_ROWS = 6
OTHER_COLS = 22


def _index():
    return device_maps.load_index(FIXTURE_ROOT)


def test_index_reads_entries_and_skips_incomplete_ones():
    index = _index()
    assert index["Test Keyboard (en_GB)"] == DeviceMap("Test Keyboard (en_GB)", GB_SVG,
                                                       ROWS, COLS, "en_GB")
    assert "Test Broken" not in index


def test_exact_key_beats_locale():
    found = device_maps.match(BOARD, ROWS, COLS, _index(), locale="en_US")
    assert found is not None and found.name == BOARD


def test_locale_suffixed_match_prefers_locale():
    found = device_maps.match(KEYBOARD, ROWS, COLS, _index(), locale="en_GB")
    assert found is not None and found.filename == GB_SVG


def test_match_is_trimmed_and_case_insensitive():
    found = device_maps.match("  test KEYBOARD ", ROWS, COLS, _index(), locale="en_GB")
    assert found is not None and found.filename == GB_SVG


def test_unknown_locale_falls_back_to_en_us():
    found = device_maps.match(KEYBOARD, ROWS, COLS, _index(), locale="fr_FR")
    assert found is not None and found.filename == US_SVG


def test_rows_cols_mismatch_gives_none():
    assert device_maps.match(KEYBOARD, ROWS + 1, COLS, _index(), locale="en_US") is None
    assert device_maps.match(KEYBOARD, ROWS, COLS + 1, _index(), locale="en_US") is None


def test_unknown_name_gives_none():
    assert device_maps.match("Toaster", ROWS, COLS, _index(), locale="en_US") is None


def test_missing_index_gives_empty(tmp_path):
    assert device_maps.load_index(tmp_path) == {}
    assert device_maps.load_index(tmp_path / "nowhere") == {}


def test_invalid_index_gives_empty(tmp_path):
    (tmp_path / "maps.json").write_text("{not json", encoding="utf-8")
    assert device_maps.load_index(tmp_path) == {}
    (tmp_path / "maps.json").write_text("[1, 2]", encoding="utf-8")
    assert device_maps.load_index(tmp_path) == {}


def test_svg_bytes_reads_the_file():
    data = device_maps.svg_bytes(_index()["Test Keyboard (en_US)"], FIXTURE_ROOT)
    assert data is not None and b'id="x0-y0"' in data


def test_svg_bytes_of_missing_file_gives_none():
    missing = DeviceMap("Ghost", "missing.xml", ROWS, COLS, None)
    assert device_maps.svg_bytes(missing, FIXTURE_ROOT) is None


def test_default_index_never_raises():
    assert isinstance(device_maps.load_index(), dict)


def test_alias_used_only_without_direct_candidate(monkeypatch):
    """An alias target draws a name with no map, never one that has its own."""
    monkeypatch.setattr(device_maps, "MAP_ALIASES", TEST_ALIASES)
    aliased = device_maps.match(GADGET, ROWS, COLS, _index(), locale="en_US")
    assert aliased is not None and aliased.name == BOARD
    direct = device_maps.match(KEYBOARD, ROWS, COLS, _index(), locale="en_GB")
    assert direct is not None and direct.name == "Test Keyboard (en_GB)"


def test_alias_with_other_matrix_size_gives_none(monkeypatch):
    """The alias retry keeps the rows/cols check."""
    monkeypatch.setattr(device_maps, "MAP_ALIASES", TEST_ALIASES)
    assert device_maps.match(GADGET, ROWS + 1, COLS, _index(), locale="en_US") is None
    assert device_maps.match(GADGET, ROWS, COLS + 1, _index(), locale="en_US") is None


def test_blackwidow_v4_uses_the_v4_pro_map():
    """The packaged index draws the BlackWidow V4 with the 8x23 V4 Pro map only."""
    if not device_maps.load_index():
        pytest.skip("no packaged device maps")
    found = device_maps.match(V4, V4_ROWS, V4_COLS, locale="en_US")
    assert found is not None and found.filename == V4_PRO_SVG
    assert device_maps.match(V4, OTHER_ROWS, OTHER_COLS, locale="en_US") is None
