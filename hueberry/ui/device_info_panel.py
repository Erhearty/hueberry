# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Read-only form showing a device's name, type, serial and versions."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFormLayout, QLabel, QVBoxLayout, QWidget

from hueberry.backend.devices import DeviceInfo
from hueberry.ui import layouts

PLACEHOLDER = "\u2014"
# (DeviceInfo attribute, label text)
FIELDS = (
    ("name", "Name:"),
    ("type", "Type:"),
    ("serial", "Serial:"),
    ("firmware_version", "Firmware:"),
    ("driver_version", "Driver:"),
)


class DeviceInfoPanel(QWidget):
    """Shows the fields of a :class:`DeviceInfo` as selectable text."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        card, card_layout = layouts.section_card("Device", self)
        layout = QFormLayout()
        layouts.configure_form(layout)
        card_layout.addLayout(layout)
        outer = QVBoxLayout(self)
        outer.addWidget(card)
        outer.addStretch(1)
        self.values: dict[str, QLabel] = {}
        for attr, text in FIELDS:
            value = QLabel(PLACEHOLDER, card)
            value.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            value.setAccessibleName(text.rstrip(":"))
            layout.addRow(text, value)
            self.values[attr] = value

    def set_device(self, info: DeviceInfo | None) -> None:
        """Display ``info``, or placeholders when it is None."""
        for attr, label in self.values.items():
            label.setText(PLACEHOLDER if info is None else str(getattr(info, attr)))
