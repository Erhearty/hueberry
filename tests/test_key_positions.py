# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the evdev key code to LED matrix table."""

import pytest

from hueberry.backend.key_positions import (
    STANDARD_COLS, STANDARD_POSITIONS, STANDARD_ROWS, position_for,
)

KEY_ESC = 1
KEY_W = 17
KEY_A = 30
KEY_S = 31
KEY_D = 32
KEY_SPACE = 57
UNMAPPED_CODE = 240


@pytest.mark.parametrize("code, cell", [
    (KEY_ESC, (0, 1)), (KEY_W, (2, 3)), (KEY_A, (3, 2)), (KEY_S, (3, 3)),
    (KEY_D, (3, 4)), (KEY_SPACE, (5, 7)),
])
def test_known_keys(code, cell):
    assert position_for(code, STANDARD_ROWS, STANDARD_COLS) == cell


def test_unmapped_code_is_none():
    assert position_for(UNMAPPED_CODE, STANDARD_ROWS, STANDARD_COLS) is None


@pytest.mark.parametrize("rows, cols", [(1, 1), (6, 18), (9, 22)])
def test_other_shapes_are_none(rows, cols):
    assert position_for(KEY_ESC, rows, cols) is None


def test_cells_are_inside_the_matrix_and_unique():
    cells = list(STANDARD_POSITIONS.values())
    assert len(set(cells)) == len(cells)
    assert all(0 <= row < STANDARD_ROWS and 0 <= col < STANDARD_COLS for row, col in cells)
