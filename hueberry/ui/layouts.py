# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Shared layout helpers so every page has the same margins, header and form look.

All sizes come from the spacing tokens in :mod:`hueberry.ui.theme`.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFormLayout, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from hueberry.ui import theme


def page_layout(widget: QWidget) -> QVBoxLayout:
    """Install and return the outer page layout of ``widget`` (page margins and spacing)."""
    layout = QVBoxLayout(widget)
    margin = theme.PAGE_MARGIN_PX
    layout.setContentsMargins(margin, margin, margin, margin)
    layout.setSpacing(theme.SPACING_M)
    return layout


def page_header(back_button: QWidget, title_label: QLabel, *extras: QWidget) -> QHBoxLayout:
    """Return a header row: back button, title (title role), a stretch, then ``extras``."""
    theme.set_role(title_label, "title")
    theme.uppercase(title_label)
    header = QHBoxLayout()
    header.setSpacing(theme.SPACING_M)
    header.addWidget(back_button)
    header.addWidget(title_label)
    header.addStretch(1)
    for widget in extras:
        header.addWidget(widget)
    return header


def configure_form(form: QFormLayout) -> None:
    """Right-align labels, let fields grow, and apply the form spacing tokens."""
    form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    form.setHorizontalSpacing(theme.SPACING_M)
    form.setVerticalSpacing(theme.SPACING_S)


def section_card(title: str, parent: QWidget | None = None) -> tuple[QFrame, QVBoxLayout]:
    """Return a styled section card and its layout, whose first item is the ``title`` header."""
    card = QFrame(parent)
    card.setObjectName(theme.SECTION_OBJECT_NAME)
    card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    layout = QVBoxLayout(card)
    padding = theme.CARD_PADDING_PX
    layout.setContentsMargins(padding, padding, padding, padding)
    layout.setSpacing(theme.SPACING_S)
    header = QLabel(title, card)
    theme.set_role(header, "section")
    theme.uppercase(header)
    layout.addWidget(header)
    return card, layout
