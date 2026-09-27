# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Per-device page: back button + name header, a hero column and Lighting/Performance/Info tabs."""

from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from hueberry.backend.devices import DeviceInfo
from hueberry.ui.device_icons import pixmap_for_type
from hueberry.ui import layouts, presets_preview, theme
from hueberry.ui import lighting_preview as preview_mapping
from hueberry.ui.device_info_panel import DeviceInfoPanel
from hueberry.ui.led_preview import LedPreview
from hueberry.ui.lighting_panel import LightingPanel
from hueberry.ui.mouse_panel import MousePanel

BACK_TEXT = "\u2190 Devices"
BACK_SHORTCUTS = ("Alt+Left", "Escape")
BACK_TIP = "Back to all devices (Alt+Left or Esc)"
TAB_LIGHTING = "Li&ghting"
TAB_PERFORMANCE = "Pe&rformance"
TAB_INFO = "&Info"
PERFORMANCE_TAB_INDEX = 1
HERO_WIDTH_PX = 220  # fixed width of the device image column
HERO_ICON_SIZE = 160  # device image size in the hero column
PREVIEW_ACCESSIBLE_NAME = "Lighting preview"


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
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label = QLabel(self)
        self.name_label.setTextFormat(Qt.TextFormat.PlainText)
        self.type_label = QLabel(self)
        self.type_label.setTextFormat(Qt.TextFormat.PlainText)
        self.type_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        theme.set_role(self.type_label, "muted")
        self.lighting_preview = LedPreview(self)
        self.lighting_preview.setAccessibleName(PREVIEW_ACCESSIBLE_NAME)
        self.lighting_preview.setVisible(False)
        self._build_tabs()
        self.lighting_panel.preview_changed.connect(self._refresh_preview)
        self._build_layout()
        self._build_shortcuts()
        QWidget.setTabOrder(self.back_button, self.tabs)

    def _build_tabs(self) -> None:
        self.info_panel = DeviceInfoPanel(self)
        self.lighting_panel = LightingPanel(self)
        self.mouse_page = QWidget(self)
        self.mouse_panel = MousePanel(self.mouse_page)
        mouse_layout = QVBoxLayout(self.mouse_page)
        mouse_layout.setContentsMargins(0, 0, 0, 0)  # align Performance with Lighting
        mouse_layout.addWidget(self.mouse_panel)
        self.tabs = QTabWidget(self)
        self.tabs.setDocumentMode(True)
        theme.uppercase(self.tabs.tabBar())
        self.tabs.addTab(self.lighting_panel, TAB_LIGHTING)
        self.tabs.addTab(self.mouse_page, TAB_PERFORMANCE)
        self.tabs.addTab(self.info_panel, TAB_INFO)

    def _build_hero(self) -> QWidget:
        """Return the fixed-width left column: device image, type and lighting preview."""
        hero = QWidget(self)
        hero.setFixedWidth(HERO_WIDTH_PX)
        column = QVBoxLayout(hero)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(theme.SPACING_S)
        column.addWidget(self.icon_label)
        column.addWidget(self.type_label)
        column.addWidget(self.lighting_preview)
        column.addStretch(1)
        return hero

    def _build_layout(self) -> None:
        header = layouts.page_header(self.back_button, self.name_label)
        body = QHBoxLayout()
        body.setSpacing(theme.SPACING_M)
        body.addWidget(self._build_hero())
        body.addWidget(self.tabs, 1)
        outer = layouts.page_layout(self)
        outer.addLayout(header)
        outer.addLayout(body, 1)

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
        self.type_label.setText(info.type if info is not None else "")
        pixmap = pixmap_for_type(info.type, HERO_ICON_SIZE) if info is not None else QPixmap()
        self.icon_label.setPixmap(pixmap)
        self.info_panel.set_device(info)
        self.lighting_panel.set_device(dev)
        self._update_preview_device(dev, info)
        self.mouse_panel.set_device(dev if is_mouse else None)
        self._set_performance_tab(is_mouse)

    def _update_preview_device(self, dev: Any, info: DeviceInfo | None) -> None:
        """Show ``dev`` in the hero preview; hidden when it has no lighting target."""
        shown = None
        if dev is not None and info is not None:
            shown = presets_preview.preview_device(dev, info)
        self.lighting_preview.set_devices([shown] if shown is not None else [])
        self.lighting_preview.setVisible(shown is not None)
        if shown is None:
            self.lighting_preview.set_preset(None)
            return
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        """Preview (approximately) the lighting panel's current selection."""
        self.lighting_preview.set_preset(preview_mapping.preview_preset(self.lighting_panel))

    def has_performance_tab(self) -> bool:
        """True when the Performance tab is currently shown."""
        return self.tabs.indexOf(self.mouse_page) >= 0

    def _set_performance_tab(self, present: bool) -> None:
        index = self.tabs.indexOf(self.mouse_page)
        if present and index < 0:
            self.tabs.insertTab(PERFORMANCE_TAB_INDEX, self.mouse_page, TAB_PERFORMANCE)
        elif not present and index >= 0:
            self.tabs.removeTab(index)
