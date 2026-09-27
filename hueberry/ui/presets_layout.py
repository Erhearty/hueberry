# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Section-card layout of the presets page: Presets, Editor and 'Apply to devices'.

The functions only arrange the widgets a :class:`~hueberry.ui.presets_page.PresetsPage`
has already built; they create no behaviour of their own.
"""

from typing import Any

from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel

from hueberry.ui import layouts, theme

LIBRARY_STRETCH = 1  # the Presets card's share of the body width
EDITOR_STRETCH = 2   # the Editor card's share of the body width
DEVICES_LABEL_TEXT = "Apply t&o:"


def _library_card(page: Any) -> QFrame:
    """Return the Presets card: the preset list, then New/Duplicate/Delete/Save."""
    card, layout = layouts.section_card("Presets", page)
    buttons = QHBoxLayout()
    buttons.setSpacing(theme.SPACING_S)
    for button in (page.new_button, page.duplicate_button, page.delete_button,
                   page.save_button):
        buttons.addWidget(button)
    layout.addWidget(page.preset_list, 1)
    layout.addLayout(buttons)
    return card


def _editor_card(page: Any) -> QFrame:
    """Return the Editor card holding the preset editor with its live preview."""
    card, layout = layouts.section_card("Editor", page)
    layout.addLayout(page.preview.editor_column(page.editor), 1)
    return card


def build_body(page: Any) -> QHBoxLayout:
    """Return the page body: the Presets card next to the Editor card."""
    body = QHBoxLayout()
    body.setSpacing(theme.SPACING_M)
    body.addWidget(_library_card(page), LIBRARY_STRETCH)
    body.addWidget(_editor_card(page), EDITOR_STRETCH)
    return body


def apply_card(page: Any) -> QFrame:
    """Return the 'Apply to devices' card: device list, then mode radios and Stop/Apply."""
    card, layout = layouts.section_card("Apply to devices", page)
    devices_label = QLabel(DEVICES_LABEL_TEXT, card)
    devices_label.setBuddy(page.device_list)
    row = QHBoxLayout()
    row.setSpacing(theme.SPACING_S)
    row.addWidget(page.single_radio)
    row.addWidget(page.group_radio)
    row.addStretch(1)
    row.addWidget(page.stop_button)
    row.addWidget(page.apply_button)
    layout.addWidget(devices_label)
    layout.addWidget(page.device_list)
    layout.addLayout(row)
    return card
