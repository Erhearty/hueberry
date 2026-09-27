#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Fetch Polychromatic's device maps (maps.json + SVGs) into the package.

The graphics are GPL-3.0 artwork from https://github.com/polychromatic/polychromatic,
pinned to :data:`COMMIT`. The script is resumable: files already present are
skipped, and ``--limit`` caps how many files one run downloads.

Usage::

    python scripts/fetch_devicemaps.py [--limit N] [--dest DIR]
"""

import argparse
import json
import logging
import sys
import urllib.request
from pathlib import Path

COMMIT = "f2def5837dec76bf3d5585894ec5b925994ddb0c"
BASE_URL = (
    "https://raw.githubusercontent.com/polychromatic/polychromatic/"
    f"{COMMIT}/data/devicemaps/"
)
INDEX_NAME = "maps.json"
DEFAULT_DEST = Path(__file__).resolve().parent.parent / "hueberry" / "data" / "devicemaps"
TIMEOUT_S = 10

log = logging.getLogger("fetch_devicemaps")


def _download(name: str, dest: Path) -> bool:
    """Download ``name`` into ``dest`` unless present; return True if fetched."""
    target = dest / name
    if target.exists():
        return False
    with urllib.request.urlopen(BASE_URL + name, timeout=TIMEOUT_S) as resp:
        data = resp.read()
    tmp = target.with_suffix(target.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(target)
    log.info("fetched file=%s bytes=%d", name, len(data))
    return True


def svg_names(index_path: Path) -> list[str]:
    """Return the sorted, unique SVG filenames referenced by the index."""
    index = json.loads(index_path.read_text(encoding="utf-8"))
    return sorted({entry["filename"] for entry in index.values()})


def fetch(dest: Path, limit: int | None) -> int:
    """Fetch the index and up to ``limit`` missing SVGs; return files remaining."""
    dest.mkdir(parents=True, exist_ok=True)
    _download(INDEX_NAME, dest)
    missing = [n for n in svg_names(dest / INDEX_NAME) if not (dest / n).exists()]
    batch = missing if limit is None else missing[:limit]
    for name in batch:
        _download(name, dest)
    return len(missing) - len(batch)


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=None, help="max SVGs per run")
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST, help="target directory")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    remaining = fetch(args.dest, args.limit)
    log.info("done remaining=%d commit=%s", remaining, COMMIT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
