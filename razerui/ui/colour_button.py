# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 RazerUI contributors
"""A push button that shows a colour swatch and opens a QColorDialog."""

import logging

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QColorDialog, QPushButton, QWidget

logger = logging.getLogger(__name__)

RGB = tuple[int, int, int]
# ITU-R BT.601 luma weights, used to pick readable text on the swatch.
LUMA_WEIGHTS = (0.299, 0.587, 0.114)
LUMA_THRESHOLD = 128
DARK_TEXT = "#000000"
LIGHT_TEXT = "#ffffff"


def colour_hex(colour: RGB) -> str:
    """Return ``#rrggbb`` for an (r, g, b) tuple."""
    red, green, blue = colour
    return f"#{red:02x}{green:02x}{blue:02x}"


def _text_colour(colour: RGB) -> str:
    luma = sum(weight * value for weight, value in zip(LUMA_WEIGHTS, colour))
    return DARK_TEXT if luma >= LUMA_THRESHOLD else LIGHT_TEXT


class ColourButton(QPushButton):
    """Button showing ``colour`` as its background; click to choose a new one."""

    colour_changed = pyqtSignal(object)

    def __init__(self, role: str, colour: RGB, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._role = role
        self._colour: RGB = colour
        self.clicked.connect(self._on_clicked)
        self._refresh()

    def colour(self) -> RGB:
        """The current (r, g, b) colour."""
        return self._colour

    def set_colour(self, colour: RGB) -> None:
        """Set the colour, update the swatch and emit ``colour_changed``."""
        red, green, blue = (int(value) for value in colour)
        self._colour = (red, green, blue)
        self._refresh()
        self.colour_changed.emit(self._colour)

    def pick_colour(self) -> QColor | None:
        """Ask the user for a colour; None when cancelled. Overridable in tests."""
        chosen = QColorDialog.getColor(QColor(*self._colour), self, f"Choose {self._role.lower()}")
        return chosen if chosen.isValid() else None

    def _on_clicked(self) -> None:
        try:
            chosen = self.pick_colour()
        except Exception:  # never let an exception escape a slot
            logger.exception("Colour selection failed")
            return
        if chosen is not None:
            self.set_colour((chosen.red(), chosen.green(), chosen.blue()))

    def _refresh(self) -> None:
        hex_value = colour_hex(self._colour)
        self.setText(hex_value)
        self.setStyleSheet(
            f"QPushButton {{ background-color: {hex_value}; color: {_text_colour(self._colour)}; }}"
        )
        self.setAccessibleName(f"{self._role} {hex_value}")
        self.setToolTip(f"{self._role}: {hex_value} (click to change)")
