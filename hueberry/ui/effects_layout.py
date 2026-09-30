# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Widgets and device scanning of the Effects page (:mod:`hueberry.ui.effects_page`)."""

import logging
from dataclasses import dataclass
from typing import Any

from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QStackedWidget, QWidget,
)

from hueberry.backend import device_maps
from hueberry.backend.advanced_presets import MAX_LABEL_LENGTH
from hueberry.backend.animator_targets import KIND_MATRIX, build_target
from hueberry.ui import layouts, theme
from hueberry.ui.effects_groups import GroupsPanel
from hueberry.ui.key_selector import KeySelector

try:  # QtSvg is a separate package on some distros; without it, draw the grid
    from hueberry.ui.device_graphic import DeviceGraphic
except ImportError:  # pragma: no cover - depends on the installed Qt modules
    DeviceGraphic = None

__all__ = ["MatrixDevice", "build", "make_selector", "matrix_devices"]

logger = logging.getLogger(__name__)

TITLE_TEXT = "Create effect"
BACK_TEXT = "\u2190 Back"
NO_DEVICES_TEXT = "No per-key keyboards found"
DEVICE_LIST_WIDTH = 200
SELECTOR_STRETCH = 1


@dataclass
class MatrixDevice:
    """A listed per-key device."""

    dev: Any
    name: str
    rows: int
    cols: int


def _graphic(name: str, rows: int, cols: int) -> Any:
    """The device-map graphic of a keyboard, or None (failures are logged)."""
    if DeviceGraphic is None:
        return None
    try:
        device_map = device_maps.match(name, rows, cols)
        data = device_maps.svg_bytes(device_map) if device_map is not None else None
        return DeviceGraphic(data) if data is not None else None
    except (ValueError, OSError) as exc:
        logger.warning("No device graphic for %s: %s", name, exc)
        return None


def matrix_devices(entries: list[tuple[Any, Any]]) -> dict[str, MatrixDevice]:
    """The per-key devices among ``(device, DeviceInfo)`` entries, by serial."""
    found: dict[str, MatrixDevice] = {}
    for dev, info in entries:
        try:
            target = build_target(dev)
        except Exception:  # D-Bus errors must not break the page
            logger.warning("Could not read the key matrix of %s", info.serial, exc_info=True)
            continue
        if target is not None and target.kind == KIND_MATRIX:
            found[info.serial] = MatrixDevice(dev, info.name or info.serial,
                                              target.rows, target.cols)
    return found


def make_selector(device: MatrixDevice, parent: QWidget) -> KeySelector:
    """A key selector of ``device`` (with its device-map graphic when there is one)."""
    return KeySelector(device.rows, device.cols, _graphic(device.name, device.rows, device.cols),
                       device.name, parent)


def build(page: Any) -> None:
    """Create the page's widgets as attributes of ``page`` and lay them out."""
    page.back_button = QPushButton(BACK_TEXT, page)
    page.title_label = QLabel(TITLE_TEXT, page)
    page.error_label = QLabel(page)
    page.error_label.setWordWrap(True)
    theme.set_role(page.error_label, "error")
    page.preset_combo = QComboBox(page)
    page.preset_combo.setAccessibleName("Per-key effect presets")
    page.label_edit = QLineEdit(page)
    page.label_edit.setMaxLength(MAX_LABEL_LENGTH)
    page.label_edit.setAccessibleName("Preset name")
    page.new_button = QPushButton("Ne&w", page)
    page.save_button = QPushButton("&Save", page)
    page.save_as_button = QPushButton("Save &as", page)
    page.delete_button = QPushButton("&Delete", page)
    page.activate_button = QPushButton("A&ctivate", page)
    theme.set_role(page.activate_button, "primary")
    page.stop_button = QPushButton("S&top", page)
    page.device_list = QListWidget(page)
    page.device_list.setAccessibleName("Per-key devices")
    page.device_list.setMaximumWidth(DEVICE_LIST_WIDTH)
    page.selector_stack = QStackedWidget(page)
    page.empty_label = QLabel(NO_DEVICES_TEXT, page.selector_stack)
    page.selector_stack.addWidget(page.empty_label)
    page.groups = GroupsPanel(page)
    _lay_out(page)


def _lay_out(page: Any) -> None:
    outer = layouts.page_layout(page)
    outer.addLayout(layouts.page_header(page.back_button, page.title_label))
    outer.addWidget(page.error_label)
    toolbar = QHBoxLayout()
    for widget in (page.preset_combo, page.label_edit, page.new_button, page.save_button,
                   page.save_as_button, page.delete_button, page.activate_button,
                   page.stop_button):
        toolbar.addWidget(widget)
    outer.addLayout(toolbar)
    body = QHBoxLayout()
    body.addWidget(page.device_list)
    body.addWidget(page.selector_stack, SELECTOR_STRETCH)
    body.addWidget(page.groups)
    outer.addLayout(body, SELECTOR_STRETCH)
