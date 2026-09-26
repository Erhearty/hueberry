# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Wiring of the live LED preview into the Presets page.

Kept apart from :mod:`hueberry.ui.presets_page` so that module stays small.
:class:`PresetsPreview` owns the :class:`LedPreview` shown under the preset
editor and keeps it in step with the page: the editor's current (unsaved)
preset, the ticked devices of the 'Apply to' list (every listed device while
none is ticked) and the "Synced group" radio.
"""

import logging
from typing import Any

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from hueberry.backend.animator_targets import build_target
from hueberry.ui.led_preview import MODE_GROUP, MODE_SINGLE, LedPreview, PreviewDevice

__all__ = ["PresetsPreview", "preview_device"]

logger = logging.getLogger(__name__)

PREVIEW_STRETCH = 1  # the preview takes the editor column's spare height


def preview_device(dev: Any, info: Any) -> PreviewDevice | None:
    """The preview entry of a ``(device, DeviceInfo)`` pair, or None when it shows no preset."""
    try:
        target = build_target(dev)
    except Exception:  # D-Bus errors must not break the page
        logger.warning("Could not read the LED shape of %s", info.serial, exc_info=True)
        return None
    if target is None:
        return None
    return PreviewDevice(info.serial, info.name or info.serial, info.type, target.shape())


class PresetsPreview(QObject):
    """Keeps a :class:`LedPreview` in step with a PresetsPage's editor, ticks and mode."""

    def __init__(self, page: Any) -> None:
        super().__init__(page)
        self._page = page
        self._entries: list[PreviewDevice] = []  # every listed device, in list order
        self.widget = LedPreview(page)
        page.editor.preset_changed.connect(self.widget.set_preset)
        page.device_list.itemChanged.connect(self._on_ticks_changed)
        page.group_radio.toggled.connect(self._on_mode_changed)
        self._on_mode_changed()

    def editor_column(self, editor: QWidget) -> QVBoxLayout:
        """A column with ``editor`` above the preview."""
        column = QVBoxLayout()
        column.addWidget(editor)
        column.addWidget(self.widget, PREVIEW_STRETCH)
        return column

    def set_entries(self, entries: list[tuple[Any, Any]]) -> list[tuple[Any, Any]]:
        """Take the page's ``(device, DeviceInfo)`` entries; return those that show presets.

        Each device's LED shape is read once, here. The preview is not
        refreshed: call :meth:`refresh_devices` once the page lists the result.
        """
        self._entries = []
        shown: list[tuple[Any, Any]] = []
        for dev, info in entries:
            preview = preview_device(dev, info)
            if preview is not None:
                self._entries.append(preview)
                shown.append((dev, info))
        return shown

    def refresh_devices(self) -> None:
        """Preview the ticked devices, or every listed one while none is ticked."""
        ticked = set(self._page.checked_serials())
        chosen = [entry for entry in self._entries if entry.serial in ticked]
        self.widget.set_devices(chosen or self._entries)

    def refresh_preset(self) -> None:
        """Preview the editor's current preset (``set_preset`` there is silent)."""
        self.widget.set_preset(self._page.editor.preset())

    def _on_ticks_changed(self, *_args: object) -> None:
        self.refresh_devices()

    def _on_mode_changed(self, *_args: object) -> None:
        self.widget.set_mode(MODE_GROUP if self._page.group_radio.isChecked() else MODE_SINGLE)
