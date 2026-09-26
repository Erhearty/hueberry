# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Where each device's LEDs sit on the shared grid an effect is drawn on.

A run of a preset paints one virtual grid. A device alone owns the whole
grid; a synced group places its devices side by side, left to right in the
given order, so a wave travels from one device into the next. A device
without a key matrix (zones only) occupies a 2x2 footprint and its single
colour is the LED at the far corner ``(1, 1)`` of that footprint - alone, it
is the corner of a 2x2 grid, exactly as the original Erheart zone maths.

Pure maths only: nothing here imports openrazer or PyQt6.
"""

from dataclasses import dataclass
from typing import Iterable

ZONE_ROWS = 2  # footprint of a zone-only device
ZONE_COLS = 2
ZONE_ROW = 1  # its one LED: the far corner of the footprint
ZONE_COL = 1
ZONE_LED_ROWS = 1  # a zone device is rendered as a 1x1 frame
ZONE_LED_COLS = 1
MIN_SPAN = 1  # guards the position maths against single-row / single-column grids
POSITION_AXES = 2  # the diagonal position is the mean of row and column fractions


def grid_position(row: int, col: int, rows: int, cols: int) -> float:
    """Diagonal position of a key in 0..1: the mean of its row and column fractions."""
    return (row / max(rows - 1, MIN_SPAN) + col / max(cols - 1, MIN_SPAN)) / POSITION_AXES


@dataclass(frozen=True)
class DeviceShape:
    """The LED shape of one device: a ``rows`` x ``cols`` matrix, or zones only."""

    serial: str
    rows: int = ZONE_ROWS
    cols: int = ZONE_COLS
    matrix: bool = False

    @classmethod
    def of_matrix(cls, serial: str, rows: int, cols: int) -> "DeviceShape":
        """A per-key matrix device."""
        if rows < MIN_SPAN or cols < MIN_SPAN:
            raise ValueError(f"matrix of {serial} must be at least 1x1, got {rows}x{cols}")
        return cls(serial, rows, cols, True)

    @classmethod
    def of_zones(cls, serial: str) -> "DeviceShape":
        """A device that shows one colour (on every zone)."""
        return cls(serial)


@dataclass(frozen=True)
class Placement:
    """A device's footprint on the grid: ``cols`` columns from ``col_offset``."""

    shape: DeviceShape
    col_offset: int

    @property
    def serial(self) -> str:
        """Serial of the placed device."""
        return self.shape.serial

    @property
    def led_rows(self) -> int:
        """Rows of the frame rendered for this device."""
        return self.shape.rows if self.shape.matrix else ZONE_LED_ROWS

    @property
    def led_cols(self) -> int:
        """Columns of the frame rendered for this device."""
        return self.shape.cols if self.shape.matrix else ZONE_LED_COLS

    def grid_cell(self, row: int, col: int) -> tuple[int, int]:
        """Grid ``(row, col)`` of the device's LED ``(row, col)``."""
        if not self.shape.matrix:
            return ZONE_ROW, self.col_offset + ZONE_COL
        return row, self.col_offset + col


@dataclass(frozen=True)
class Layout:
    """The virtual grid of one run and where each device sits on it."""

    rows: int
    cols: int
    placements: tuple[Placement, ...]

    def serials(self) -> tuple[str, ...]:
        """Serials in placement (left to right) order."""
        return tuple(placement.serial for placement in self.placements)

    def position(self, placement: Placement, row: int, col: int) -> float:
        """Diagonal position (0..1) of a device LED on the whole grid."""
        grid_row, grid_col = placement.grid_cell(row, col)
        return grid_position(grid_row, grid_col, self.rows, self.cols)

    def hue_position(self, placement: Placement, pos: float) -> float:
        """Where the LED at ``pos`` samples a palette.

        A zone device wraps its position (the far corner, 1.0, becomes 0.0),
        so alone it samples the palette at the phase itself - byte for byte
        the original Erheart zone colour. Matrix keys use ``pos`` unchanged.
        """
        return pos if placement.shape.matrix else pos % 1


def group_layout(shapes: Iterable[DeviceShape]) -> Layout:
    """Place ``shapes`` side by side in order; a single shape owns the whole grid.

    Raises ValueError for an empty group or a serial listed twice.
    """
    shapes = list(shapes)
    if not shapes:
        raise ValueError("a layout needs at least one device")
    serials = [shape.serial for shape in shapes]
    if len(set(serials)) != len(serials):
        raise ValueError("a device can appear only once in a layout")
    placements = []
    offset = 0
    for shape in shapes:
        placements.append(Placement(shape, offset))
        offset += shape.cols
    return Layout(max(shape.rows for shape in shapes), offset, tuple(placements))


def single_layout(shape: DeviceShape) -> Layout:
    """The layout of one device on its own."""
    return group_layout([shape])
