# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the shared page/header/form layout helpers (offscreen)."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QFormLayout, QFrame, QLabel, QPushButton, QWidget

from hueberry.ui import layouts, theme


def test_page_layout_margins_and_spacing(qtbot):
    widget = QWidget()
    qtbot.addWidget(widget)
    layout = layouts.page_layout(widget)
    assert widget.layout() is layout
    margins = layout.contentsMargins()
    margin = theme.PAGE_MARGIN_PX
    assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (
        margin, margin, margin, margin)
    assert layout.spacing() == theme.SPACING_M


def test_page_header_order_and_title_role(qtbot):
    widget = QWidget()
    qtbot.addWidget(widget)
    back = QPushButton("Back", widget)
    title = QLabel("Title", widget)
    extra = QPushButton("Reload", widget)
    header = layouts.page_header(back, title, extra)
    assert title.property("role") == "title"
    assert header.itemAt(0).widget() is back
    assert header.itemAt(1).widget() is title
    assert header.itemAt(2).spacerItem() is not None
    assert header.itemAt(3).widget() is extra
    assert header.count() == 4


def test_page_header_title_is_uppercase(qtbot):
    widget = QWidget()
    qtbot.addWidget(widget)
    title = QLabel("Title", widget)
    layouts.page_header(QPushButton("Back", widget), title)
    assert title.font().capitalization() == QFont.Capitalization.AllUppercase


def test_configure_form(qtbot):
    widget = QWidget()
    qtbot.addWidget(widget)
    form = QFormLayout(widget)
    layouts.configure_form(form)
    expected = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    assert form.labelAlignment() == expected
    assert form.fieldGrowthPolicy() == QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
    assert form.horizontalSpacing() == theme.SPACING_M
    assert form.verticalSpacing() == theme.SPACING_S


def test_section_card_object_name_and_parent(qtbot):
    parent = QWidget()
    qtbot.addWidget(parent)
    card, layout = layouts.section_card("Effect", parent)
    assert isinstance(card, QFrame)
    assert card.parent() is parent
    assert card.objectName() == theme.SECTION_OBJECT_NAME
    assert card.testAttribute(Qt.WidgetAttribute.WA_StyledBackground)
    assert card.layout() is layout


def test_section_card_margins_and_spacing(qtbot):
    card, layout = layouts.section_card("Effect")
    qtbot.addWidget(card)
    margins = layout.contentsMargins()
    padding = theme.CARD_PADDING_PX
    assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (
        padding, padding, padding, padding)
    assert layout.spacing() == theme.SPACING_S


def test_section_card_header_is_first_and_uppercase(qtbot):
    card, layout = layouts.section_card("Effect")
    qtbot.addWidget(card)
    header = layout.itemAt(0).widget()
    assert isinstance(header, QLabel)
    assert header.text() == "Effect"
    assert header.property("role") == "section"
    assert header.font().capitalization() == QFont.Capitalization.AllUppercase
