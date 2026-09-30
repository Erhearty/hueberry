# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the key watch: name matching, key-down filter, ring buffer and cursor."""

from types import SimpleNamespace

import pytest

from hueberry.macro_engine.key_watch import KeyWatch, parse_names, parse_since

KEY_A, KEY_B = 30, 48
SMALL_BUFFER = 3


def _entry(name):
    return SimpleNamespace(name=name)


def test_matches_case_insensitive_substring():
    """Any configured name matching as a case-insensitive substring counts."""
    watch = KeyWatch()
    watch.set_names(["naga", "G502"])
    assert watch.matches("Razer Naga Pro")
    assert watch.matches("Logitech g502 HERO")
    assert not watch.matches("Keyboard")


def test_empty_names_match_nothing():
    """No names (or only empty strings) match nothing."""
    watch = KeyWatch()
    assert not watch.matches("Razer Naga")
    watch.set_names([""])
    assert not watch.matches("Razer Naga")


def test_wanted_filters_entries():
    """wanted keeps entries whose name matches, in order."""
    watch = KeyWatch()
    watch.set_names(["naga"])
    entries = [_entry("Razer Naga"), _entry("Keyboard"), _entry("Razer Naga Keyboard")]
    assert watch.wanted(entries) == [entries[0], entries[2]]


def test_record_keeps_only_key_down():
    """Releases and repeats are dropped; timestamps become milliseconds."""
    watch = KeyWatch()
    watch.record(KEY_A, 1, 1.5)
    watch.record(KEY_A, 2, 1.6)
    watch.record(KEY_A, 0, 1.7)
    assert watch.events_since(0) == ([[KEY_A, 0, 1500]], 1)


def test_overflow_drops_oldest():
    """A full buffer drops the oldest events; seq keeps counting."""
    watch = KeyWatch(max_events=SMALL_BUFFER)
    for index in range(SMALL_BUFFER + 2):
        watch.record(KEY_A, 1, index)
    events, next_seq = watch.events_since(0)
    assert [seq for _code, seq, _t in events] == [2, 3, 4]
    assert next_seq == SMALL_BUFFER + 2


def test_since_cursor():
    """Polling with the returned cursor yields only new events."""
    watch = KeyWatch()
    assert watch.events_since(0) == ([], 0)
    watch.record(KEY_A, 1, 1.0)
    events, cursor = watch.events_since(0)
    assert events == [[KEY_A, 0, 1000]] and cursor == 1
    assert watch.events_since(cursor) == ([], 1)
    watch.record(KEY_B, 1, 2.0)
    assert watch.events_since(cursor) == ([[KEY_B, 1, 2000]], 2)


@pytest.mark.parametrize("args, expected", [
    ({"names": ["a", "b"]}, ["a", "b"]),
    ({"names": []}, []),
    ({"names": "a"}, None),
    ({"names": ["a", 1]}, None),
    ({}, None),
])
def test_parse_names(args, expected):
    assert parse_names(args) == expected


@pytest.mark.parametrize("args, expected", [
    ({"since": 0}, 0),
    ({"since": 7}, 7),
    ({"since": -1}, None),
    ({"since": True}, None),
    ({"since": "1"}, None),
    ({"since": 1.0}, None),
    ({}, None),
])
def test_parse_since(args, expected):
    assert parse_since(args) == expected
