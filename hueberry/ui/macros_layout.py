# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Widgets and section-card layout of the macros page: Devices, Macro engine and Macros.

The functions build and arrange the widgets of a
:class:`~hueberry.ui.macros_page.MacrosPage`; they create no behaviour of their own.
"""

from typing import Any

from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QListWidget, QPushButton, QWidget

from hueberry.ui import layouts, theme

TITLE_TEXT = "Macros"
BACK_TEXT = "\u2190 Devices"
START_ENGINE_TEXT = "Start &engine"
NO_DEVICES_TEXT = "No Razer keyboard or mouse found \u2014 connect one or start the macro engine"
NO_MACROS_TEXT = "No macros yet \u2014 press Add to create one"
NO_DEVICE_SELECTED_TEXT = "Select a device to see its macros"
DEVICES_STRETCH = 1  # the Devices card's share of the body width
MACROS_STRETCH = 2   # the Macros card's share of the body width


def _hint_label(text: str, parent: QWidget) -> QLabel:
    """A muted, word-wrapped empty-state hint."""
    label = QLabel(text, parent)
    label.setWordWrap(True)
    theme.set_role(label, "muted")
    return label


def _build_header_widgets(page: Any) -> None:
    """Back button, title, Reload, the engine banner and Start."""
    page.back_button = QPushButton(BACK_TEXT, page)
    page.title_label = QLabel(TITLE_TEXT, page)
    page.banner_label = QLabel(page)
    page.banner_label.setWordWrap(True)
    page.banner_label.setAccessibleName("Macro engine status")
    theme.set_role(page.banner_label, "error")
    page.start_button = QPushButton(START_ENGINE_TEXT, page)
    page.refresh_button = QPushButton("Re&load", page)
    page.refresh_button.setToolTip("Re-read device states from the macro engine")


def _build_list_widgets(page: Any) -> None:
    """The device and macro lists, each with its empty-state hint."""
    page.device_list = QListWidget(page)
    page.device_list.setAccessibleName("Input devices")
    page.device_empty_label = _hint_label(NO_DEVICES_TEXT, page)
    page.macro_list = QListWidget(page)
    page.macro_list.setAccessibleName("Macros of the selected device")
    page.macro_empty_label = _hint_label(NO_MACROS_TEXT, page)


def build_widgets(page: Any) -> None:
    """Create every widget of ``page`` as a page attribute."""
    _build_header_widgets(page)
    _build_list_widgets(page)
    page.add_button = QPushButton("&Add\u2026", page)
    theme.set_role(page.add_button, "primary")
    page.edit_button = QPushButton("&Edit\u2026", page)
    page.delete_button = QPushButton("&Delete", page)
    page.save_button = QPushButton("&Save", page)
    theme.set_role(page.save_button, "primary")


def _devices_card(page: Any) -> QFrame:
    """Return the Devices card: the device list and its empty-state hint."""
    card, layout = layouts.section_card("Devices", page)
    layout.addWidget(page.device_empty_label)
    layout.addWidget(page.device_list, 1)
    return card


def engine_card(page: Any) -> QFrame:
    """Return the Macro engine card: the status banner and the Start button."""
    card, layout = layouts.section_card("Macro engine", page)
    banner = QHBoxLayout()
    banner.addWidget(page.banner_label, 1)
    banner.addWidget(page.start_button)
    layout.addLayout(banner)
    return card


def _macros_card(page: Any) -> QFrame:
    """Return the Macros card: Add/Edit/Delete toolbar, the macro list, then Save."""
    card, layout = layouts.section_card("Macros", page)
    toolbar = QHBoxLayout()
    toolbar.setSpacing(theme.SPACING_S)
    for button in (page.add_button, page.edit_button, page.delete_button):
        toolbar.addWidget(button)
    toolbar.addStretch(1)
    footer = QHBoxLayout()
    footer.addStretch(1)
    footer.addWidget(page.save_button)
    layout.addLayout(toolbar)
    layout.addWidget(page.macro_empty_label)
    layout.addWidget(page.macro_list, 1)
    layout.addLayout(footer)
    return card


def build_layout(page: Any) -> None:
    """Install the page layout: header, the engine card, then Devices beside Macros."""
    header = layouts.page_header(page.back_button, page.title_label, page.refresh_button)
    body = QHBoxLayout()
    body.setSpacing(theme.SPACING_M)
    body.addWidget(_devices_card(page), DEVICES_STRETCH)
    body.addWidget(_macros_card(page), MACROS_STRETCH)
    outer = layouts.page_layout(page)
    outer.addLayout(header)
    page.engine_card = engine_card(page)
    outer.addWidget(page.engine_card)
    outer.addLayout(body, 1)
