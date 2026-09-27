# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Hueberry's licensing files are present and consistent (GPL-3.0-or-later)."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
LICENSE = REPO_ROOT / "LICENSE"
LICENSE_COPY = REPO_ROOT / "LICENSES" / "GPL-3.0-or-later.txt"
REUSE_TOML = REPO_ROOT / "REUSE.toml"
NOTICE = REPO_ROOT / "NOTICE"
PYPROJECT = REPO_ROOT / "pyproject.toml"
SPDX_ID = "GPL-3.0-or-later"
SPDX_TAG = f"SPDX-License-Identifier: {SPDX_ID}"
HEADER_LINES = 3
SOURCE_DIRS = ("hueberry", "scripts", "tests")
DEVICEMAPS_GLOB = "hueberry/data/devicemaps/**"
ENCODING = "utf-8"


def _head(path: Path) -> str:
    """The first HEADER_LINES lines of ``path``."""
    lines = path.read_text(encoding=ENCODING).splitlines()
    return "\n".join(lines[:HEADER_LINES])


def test_license_copy_is_identical():
    """LICENSES/GPL-3.0-or-later.txt is byte-identical to LICENSE."""
    assert LICENSE.read_bytes() == LICENSE_COPY.read_bytes()


def test_license_is_gpl_3():
    """LICENSE starts with the GPL version 3 title."""
    head = _head(LICENSE)
    assert "GNU GENERAL PUBLIC LICENSE" in head
    assert "Version 3" in head


def test_every_python_file_has_spdx_header():
    """Every .py file under the source dirs carries the SPDX licence header."""
    offenders = [str(path.relative_to(REPO_ROOT))
                 for folder in SOURCE_DIRS
                 for path in sorted((REPO_ROOT / folder).rglob("*.py"))
                 if SPDX_TAG not in _head(path)]
    assert offenders == []


def test_reuse_toml_covers_devicemaps():
    """REUSE.toml annotates the vendored device maps as GPL-3.0-or-later."""
    tomllib = pytest.importorskip("tomllib")
    data = tomllib.loads(REUSE_TOML.read_text(encoding=ENCODING))
    assert any(item.get("path") == DEVICEMAPS_GLOB
               and item.get("SPDX-License-Identifier") == SPDX_ID
               for item in data.get("annotations", []))


def test_notice_credits_polychromatic():
    """NOTICE credits Polychromatic under GPL-3.0-or-later."""
    text = NOTICE.read_text(encoding=ENCODING)
    assert "Polychromatic" in text
    assert SPDX_ID in text


def test_pyproject_license_metadata():
    """pyproject declares GPL-3.0-or-later and ships LICENSES/*."""
    tomllib = pytest.importorskip("tomllib")
    project = tomllib.loads(PYPROJECT.read_text(encoding=ENCODING))["project"]
    assert project["license"] == SPDX_ID
    assert "LICENSES/*" in project["license-files"]
