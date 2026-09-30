# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Select keys of one device's LED matrix with the mouse or the keyboard.

Mouse: click selects one key, Ctrl+click toggles it, Shift+click selects the
rectangle from the last clicked key, dragging draws a rubber band (with Ctrl
it adds to the selection). Keyboard: arrows move the focused key (Shift
extends a rectangle), Space toggles it, Ctrl+A selects all, Esc clears.

With a :class:`DeviceGraphic` the device map is drawn aspect-fit inside the
margin and every key is the rectangle of its LED element in that map; only
LEDs the map draws (with an element) can be selected, and a click selects the
smallest LED under the pointer. Without a graphic, or when none of its LEDs is
in the matrix, the keys are laid out on a uniform ``rows x cols`` grid.
"""

import logging
from typing import Iterable, Mapping

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPaintEvent, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from hueberry.ui.device_graphic import DeviceGraphic

__all__ = ["KeySelector"]

logger = logging.getLogger(__name__)

Cell = tuple[int, int]
RGB = tuple[int, int, int]
MARGIN = 4.0  # pixels around the key grid
CELL_INSET = 1.5  # gap between keys
MIN_CELL = 12  # minimum size hint per key, pixels
DRAG_THRESHOLD = 4  # pixels before a press becomes a rubber band
OFF_COLOUR = QColor(40, 40, 40)
SELECTED_PEN = QColor(255, 255, 255)
GROUP_PEN = QColor(160, 160, 160)
FOCUS_PEN = QColor(255, 200, 0)
BAND_FILL = QColor(80, 140, 255, 60)
SELECTED_WIDTH = 2.0
FOCUS_WIDTH = 2.0
GROUP_WIDTH = 1.0
ACCESSIBLE_NAME = "Key selector: {name}"
DESCRIPTION = "{count} of {total} keys selected; focused key row {row}, column {col}"
ARROWS = {Qt.Key.Key_Left: (0, -1), Qt.Key.Key_Right: (0, 1),
          Qt.Key.Key_Up: (-1, 0), Qt.Key.Key_Down: (1, 0)}


def _rectangle(first: Cell, second: Cell) -> set[Cell]:
    (r1, c1), (r2, c2) = first, second
    return {(r, c) for r in range(min(r1, r2), max(r1, r2) + 1)
            for c in range(min(c1, c2), max(c1, c2) + 1)}


def _led_rects(graphic: DeviceGraphic | None, grid: set[Cell]) -> dict[Cell, QRectF]:
    """The viewBox rects of the graphic's LEDs inside ``grid`` ({} without any)."""
    if graphic is None:
        return {}
    try:
        rects = graphic.led_rects()
    except Exception:  # a broken map means the plain grid
        logger.warning("Device map LED geometry unavailable", exc_info=True)
        return {}
    return {cell: rect for cell, rect in rects.items() if cell in grid}


class KeySelector(QWidget):
    """Key grid of one device; emits ``selection_changed(frozenset[(row, col)])``."""

    selection_changed = pyqtSignal(object)

    def __init__(self, rows: int, cols: int, graphic: DeviceGraphic | None = None,
                 name: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows, self._cols = max(rows, 1), max(cols, 1)
        grid = {(r, c) for r in range(self._rows) for c in range(self._cols)}
        self._led_rects = _led_rects(graphic, grid)
        self._graphic = graphic if self._led_rects else None
        self._valid = set(self._led_rects) or grid
        self._selection: set[Cell] = set()
        self._colours: dict[Cell, RGB] = {}
        self._group_of: dict[Cell, str] = {}
        self._cursor: Cell = min(self._valid)
        self._anchor: Cell = self._cursor
        self._press: QPointF | None = None
        self._band: QRectF | None = None
        self._drag_base: set[Cell] = set()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName(ACCESSIBLE_NAME.format(name=name or f"{rows}x{cols} keys"))
        self._describe()

    # -- public API --------------------------------------------------------------

    def selection(self) -> frozenset[Cell]:
        """The selected keys."""
        return frozenset(self._selection)

    def set_selection(self, cells: Iterable[Cell]) -> None:
        """Select ``cells`` (invalid ones are ignored); emits when it changed."""
        self._change({cell for cell in cells if cell in self._valid})

    def cursor(self) -> Cell:
        """The keyboard-focused key."""
        return self._cursor

    def valid_cells(self) -> frozenset[Cell]:
        """Keys that can be selected."""
        return frozenset(self._valid)

    def set_colours(self, colours: Mapping[Cell, RGB]) -> None:
        """Fill keys with these colours (others are drawn dark)."""
        self._colours = dict(colours)
        self.update()

    def set_group_outlines(self, groups: Mapping[str, Iterable[Cell]]) -> None:
        """Outline the keys of each named group."""
        self._group_of = {cell: name for name, cells in groups.items() for cell in cells}
        self.update()

    def cell_rect(self, row: int, col: int) -> QRectF:
        """The key's rectangle in widget pixels (empty for a key the map does not draw)."""
        if self._graphic is not None:
            led = self._led_rects.get((row, col))
            if led is None:
                return QRectF()
            return self._graphic.to_widget(led, self._target())
        area = self._area()
        width, height = area.width() / self._cols, area.height() / self._rows
        return QRectF(area.left() + col * width, area.top() + row * height, width, height)

    def cell_at(self, point: QPointF) -> Cell | None:
        """The selectable key under ``point`` (the smallest one when LEDs overlap), or None."""
        if self._graphic is not None:
            hits = [(self._size(cell), cell) for cell in self._valid
                    if self.cell_rect(*cell).contains(point)]
            return min(hits)[1] if hits else None
        area = self._area()
        if not area.contains(point) or area.isEmpty():
            return None
        col = int((point.x() - area.left()) / (area.width() / self._cols))
        row = int((point.y() - area.top()) / (area.height() / self._rows))
        cell = (min(row, self._rows - 1), min(col, self._cols - 1))
        return cell if cell in self._valid else None

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        """Room for every key at a readable size."""
        extra = int(2 * MARGIN)
        return QSize(self._cols * MIN_CELL * 2 + extra, self._rows * MIN_CELL * 2 + extra)

    # -- mouse -------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        """Click, Ctrl+click toggle, Shift+click rectangle; starts a possible drag."""
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        self._press = event.position()
        self._drag_base = set(self._selection) if ctrl else set()
        cell = self.cell_at(event.position())
        if cell is None:
            return
        if mods & Qt.KeyboardModifier.ShiftModifier:
            rect = _rectangle(self._anchor, cell) & self._valid
            self._change(self._drag_base | rect)
        elif ctrl:
            self._change(self._selection ^ {cell})
            self._anchor = cell
        else:
            self._change({cell})
            self._anchor = cell
        self._move_cursor(cell)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        """Qt sends the second press of a double click as this event: treat it as a press."""
        self.mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        """Grow the rubber band once the pointer moved far enough."""
        if self._press is None:
            return
        moved = event.position() - self._press
        if self._band is None and moved.manhattanLength() < DRAG_THRESHOLD:
            return
        self._band = QRectF(self._press, event.position()).normalized()
        covered = {cell for cell in self._valid if self._touches(cell, self._band)}
        self._change(self._drag_base | covered)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        """Finish a click or drag."""
        self._press, self._band = None, None
        self.update()

    # -- keyboard ----------------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override
        """Arrows, Space, Ctrl+A and Esc; anything else goes to the parent."""
        key, mods = event.key(), event.modifiers()
        if key in ARROWS:
            self._arrow(ARROWS[key], bool(mods & Qt.KeyboardModifier.ShiftModifier))
        elif key == Qt.Key.Key_Space:
            self._change(self._selection ^ {self._cursor})
            self._anchor = self._cursor
        elif key == Qt.Key.Key_A and mods & Qt.KeyboardModifier.ControlModifier:
            self._change(set(self._valid))
        elif key == Qt.Key.Key_Escape and self._selection:
            self._change(set())
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def _arrow(self, step: Cell, extend: bool) -> None:
        """Move the focused key to the next selectable one in ``step`` direction."""
        row, col = self._cursor
        while True:
            row, col = row + step[0], col + step[1]
            if not (0 <= row < self._rows and 0 <= col < self._cols):
                return
            if (row, col) in self._valid:
                break
        self._move_cursor((row, col))
        if extend:
            self._change(_rectangle(self._anchor, self._cursor) & self._valid)
        else:
            self._anchor = self._cursor

    # -- painting ----------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        """Draw the device map (if any), the keys, outlines, focus and rubber band."""
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            if self._graphic is not None:
                self._paint_graphic(painter, self._target())
            for cell in sorted(self._valid):
                self._paint_cell(painter, cell)
            if self._band is not None:
                painter.fillRect(self._band, BAND_FILL)
        finally:
            painter.end()

    def _paint_graphic(self, painter: QPainter, target: QRectF) -> None:
        """Draw the device map into ``target``, the same rect the keys are mapped onto."""
        try:
            self._graphic.paint(painter, target, self._graphic_colour)
        except Exception:  # a broken map must not break the selector
            logger.warning("Device map could not be drawn", exc_info=True)
            self._graphic = None

    def _graphic_colour(self, row: int, col: int) -> QColor | None:
        colour = self._colours.get((row, col))
        return QColor(*colour) if colour is not None else None

    def _paint_cell(self, painter: QPainter, cell: Cell) -> None:
        rect = self.cell_rect(*cell).adjusted(CELL_INSET, CELL_INSET, -CELL_INSET, -CELL_INSET)
        if self._graphic is None:
            colour = self._colours.get(cell)
            painter.fillRect(rect, QColor(*colour) if colour is not None else OFF_COLOUR)
        pens = []
        if cell in self._group_of:
            pens.append(QPen(GROUP_PEN, GROUP_WIDTH, Qt.PenStyle.DashLine))
        if cell in self._selection:
            pens.append(QPen(SELECTED_PEN, SELECTED_WIDTH))
        if cell == self._cursor and self.hasFocus():
            pens.append(QPen(FOCUS_PEN, FOCUS_WIDTH, Qt.PenStyle.DotLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for pen in pens:
            painter.setPen(pen)
            painter.drawRect(rect)

    # -- internals ---------------------------------------------------------------

    def _area(self) -> QRectF:
        """The widget inside the margin: where the uniform key grid is drawn."""
        return QRectF(self.rect()).adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN)

    def _target(self) -> QRectF:
        """Where the device map is drawn; its LED rects are mapped onto this."""
        area = self._area()
        try:
            return self._graphic.target_rect(area)
        except Exception:  # draw into the margin area instead
            logger.warning("Device map geometry unavailable", exc_info=True)
            return area

    def _size(self, cell: Cell) -> float:
        """The key's area in the device map (to pick the smallest of overlapping keys)."""
        rect = self._led_rects[cell]
        return rect.width() * rect.height()

    def _touches(self, cell: Cell, band: QRectF) -> bool:
        """True when the key overlaps ``band`` (edges included: a flat band still counts)."""
        rect = self.cell_rect(*cell)
        return (rect.left() <= band.right() and rect.right() >= band.left()
                and rect.top() <= band.bottom() and rect.bottom() >= band.top())

    def _change(self, selection: set[Cell]) -> None:
        if selection == self._selection:
            return
        self._selection = selection
        self._describe()
        self.update()
        self.selection_changed.emit(frozenset(selection))

    def _move_cursor(self, cell: Cell) -> None:
        self._cursor = cell
        self._describe()
        self.update()

    def _describe(self) -> None:
        row, col = self._cursor
        self.setAccessibleDescription(DESCRIPTION.format(
            count=len(self._selection), total=len(self._valid), row=row + 1, col=col + 1))

    def focusInEvent(self, event) -> None:  # noqa: N802 - Qt override
        """Repaint to show the focused key."""
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event) -> None:  # noqa: N802 - Qt override
        """Repaint to hide the focused key."""
        super().focusOutEvent(event)
        self.update()

