# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""The vendored Polychromatic device maps are complete and usable."""

import json
import re
import xml.etree.ElementTree as ET
from importlib.resources import files

import pytest

LED_ID = re.compile(r"^x\d+-y\d+$")
MAPS_DIR = files("hueberry.data").joinpath("devicemaps")


def _index():
    """Load the bundled maps.json via importlib.resources."""
    return json.loads(MAPS_DIR.joinpath("maps.json").read_text(encoding="utf-8"))


def _led_ids(svg_name):
    """Return the ids of every class="LED" node in a bundled SVG."""
    root = ET.fromstring(MAPS_DIR.joinpath(svg_name).read_bytes())
    return [
        el.get("id", "")
        for el in root.iter()
        if "LED" in (el.get("class") or "").split()
    ]


def test_index_loads_and_is_not_empty():
    """maps.json is present and maps names to entries with filename/rows/cols."""
    index = _index()
    assert index
    for entry in index.values():
        assert {"filename", "rows", "cols"} <= entry.keys()


@pytest.mark.parametrize("name", sorted({e["filename"] for e in _index().values()}))
def test_every_referenced_svg_exists_and_has_leds(name):
    """Each referenced SVG ships and has at least one well-formed LED id."""
    assert MAPS_DIR.joinpath(name).is_file()
    ids = _led_ids(name)
    assert any(LED_ID.match(i) for i in ids)
