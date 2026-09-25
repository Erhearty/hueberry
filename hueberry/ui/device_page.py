# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Per-device page: back button, icon + name header, and Lighting/Performance/Info tabs."""

from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTabWidget, QVBoxLayout, QWidget

from hueberry.backend.devices import DeviceInfo
from hueberry.ui.device_icons import pixmap_for_type
from hueberry.ui.device_info_panel import DeviceInfoPanel
from hueberry.ui.lighting_panel import LightingPanel
from hueberry.ui.mouse_panel import MousePanel

BACK_TEXT = "\u2190 Devices"
BACK_SHORTCUTS = ("Alt+Left", "Escape")
BACK_TIP = "Back to all devices (Alt+Left or Esc)"
TAB_LIGHTING = "Li&ghting"
TAB_PERFORMANCE = "Pe&rformance"
TAB_INFO = "&Info"
PERFORMANCE_TAB_INDEX = 1
HEADER_ICON_SIZE = 40
HEADER_FONT_SCALE = 1.4


class DevicePage(QWidget):
    """Shows one device; the Performance tab is only present for mice.

    ``back_requested`` is emitted by the back button, Alt+Left and Escape.
    """

    back_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.back_button = QPushButton(BACK_TEXT, self)
        self.back_button.setToolTip(BACK_TIP)
        self.icon_label = QLabel(self)
        self.name_label = QLabel(self)
        self.name_label.setTextFormat(Qt.TextFormat.PlainText)
        font = self.name_label.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * HEADER_FONT_SCALE)
        self.name_label.setFont(font)
        self._build_tabs()
        self._build_layout()
        self._build_shortcuts()
        QWidget.setTabOrder(self.back_button, self.tabs)

    def _build_tabs(self) -> None:
        self.info_panel = DeviceInfoPanel(self)
        self.lighting_panel = LightingPanel(self)
        self.mouse_page = QWidget(self)
        self.mouse_panel = MousePanel(self.mouse_page)
        QVBoxLayout(self.mouse_page).addWidget(self.mouse_panel)
        self.tabs = QTabWidget(self)
        self.tabs.addTab(self.lighting_panel, TAB_LIGHTING)
        self.tabs.addTab(self.mouse_page, TAB_PERFORMANCE)
        self.tabs.addTab(self.info_panel, TAB_INFO)

    def _build_layout(self) -> None:
        header = QHBoxLayout()
        header.addWidget(self.back_button)
        header.addWidget(self.icon_label)
        header.addWidget(self.name_label)
        header.addStretch(1)
        outer = QVBoxLayout(self)
        outer.addLayout(header)
        outer.addWidget(self.tabs, 1)

    def _build_shortcuts(self) -> None:
        self.back_button.clicked.connect(self.back_requested)
        self.back_shortcuts: list[QShortcut] = []
        for sequence in BACK_SHORTCUTS:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(self.back_requested)
            self.back_shortcuts.append(shortcut)

    def set_device(self, dev: Any, info: DeviceInfo | None) -> None:
        """Show ``dev`` described by ``info``; ``None`` clears the page."""
        is_mouse = info is not None and info.is_mouse
        self.name_label.setText(info.name if info is not None else "")
        pixmap = pixmap_for_type(info.type, HEADER_ICON_SIZE) if info is not None else QPixmap()
        self.icon_label.setPixmap(pixmap)
        self.info_panel.set_device(info)
        self.lighting_panel.set_device(dev)
        self.mouse_panel.set_device(dev if is_mouse else None)
        self._set_performance_tab(is_mouse)

    def has_performance_tab(self) -> bool:
        """True when the Performance tab is currently shown."""
        return self.tabs.indexOf(self.mouse_page) >= 0

    def _set_performance_tab(self, present: bool) -> None:
        index = self.tabs.indexOf(self.mouse_page)
        if present and index < 0:
            self.tabs.insertTab(PERFORMANCE_TAB_INDEX, self.mouse_page, TAB_PERFORMANCE)
        elif not present and index >= 0:
            self.tabs.removeTab(index)
