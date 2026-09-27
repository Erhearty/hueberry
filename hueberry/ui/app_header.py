# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Top app header bar: brand, navigation buttons, a stretch, then trailing widgets."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from hueberry.ui import theme

BRAND_TEXT = "HUEBERRY"


class AppHeader(QWidget):
    """Black header bar styled by ``QWidget#appHeader`` in the theme.

    Nav buttons are inserted before the stretch; trailing widgets go after it.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("appHeader")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.brand_label = QLabel(BRAND_TEXT, self)
        theme.set_role(self.brand_label, "brand")
        self._layout = QHBoxLayout(self)
        margin = theme.PAGE_MARGIN_PX
        self._layout.setContentsMargins(margin, theme.SPACING_S, margin, theme.SPACING_S)
        self._layout.setSpacing(theme.SPACING_M)
        self._layout.addWidget(self.brand_label)
        self._layout.addStretch(1)

    def _stretch_index(self) -> int:
        """Index of the stretch separating nav buttons from trailing widgets."""
        for index in range(self._layout.count()):
            if self._layout.itemAt(index).spacerItem() is not None:
                return index
        return self._layout.count()

    def add_nav(self, text: str, tip: str) -> QPushButton:
        """Add and return an uppercase nav button with tooltip ``tip`` before the stretch."""
        button = QPushButton(text, self)
        theme.set_role(button, "nav")
        theme.uppercase(button)
        button.setToolTip(tip)
        self._layout.insertWidget(self._stretch_index(), button)
        return button

    def add_trailing(self, widget: QWidget) -> None:
        """Append ``widget`` after the stretch (right-hand side of the header)."""
        self._layout.addWidget(widget)

    def header_layout(self) -> QHBoxLayout:
        """The header's row layout (brand, nav, stretch, trailing)."""
        return self._layout
