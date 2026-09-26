# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Live LED preview: the chosen devices drawn side by side, lit by a preset.

Colours come from :func:`hueberry.backend.effects.render_run` on the same
layouts the animator uses (:func:`group_layout` for a synced group,
:func:`single_layout` per device otherwise), so the preview matches the
hardware. Outlines are plain rounded rectangles sized from a table of nominal
device sizes; everything is drawn here, no vendor artwork is used. A timer
advances the phase at ``PREVIEW_FPS`` while the widget is shown, never while
it is hidden.
"""

import logging
from dataclasses import dataclass
from typing import Iterable

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QHideEvent, QPainter, QPaintEvent, QPen, QShowEvent
from PyQt6.QtWidgets import QWidget

from hueberry.backend.effects import (
    EFFECT_LABELS, RGB, Frame, Preset, advance_phase, is_animated, render_run,
)
from hueberry.backend.led_layout import DeviceShape, group_layout, single_layout
from hueberry.ui import theme

__all__ = ["LedPreview", "PreviewDevice", "nominal_size", "MODE_SINGLE", "MODE_GROUP"]

logger = logging.getLogger(__name__)

MODE_SINGLE = "single"  # every device runs the preset on its own
MODE_GROUP = "group"  # the devices form one synced group, left to right
MODE_LABELS = {MODE_SINGLE: "each device on its own", MODE_GROUP: "synced group"}
PREVIEW_FPS = 30
MS_PER_SECOND = 1000
FRAME_INTERVAL_MS = round(MS_PER_SECOND / PREVIEW_FPS)
DEFAULT_TYPE = "default"
#: Nominal outline size ``(width_mm, height_mm)`` per device type (case-insensitive).
NOMINAL_SIZE_MM: dict[str, tuple[float, float]] = {
    "keyboard": (440.0, 140.0),
    "mouse": (65.0, 125.0),
    "mousemat": (355.0, 255.0),
    "headset": (180.0, 200.0),
    "keypad": (190.0, 150.0),
    DEFAULT_TYPE: (120.0, 120.0),
}
GAP_MM = 30.0  # space between two outlines, in the units of NOMINAL_SIZE_MM
MARGIN_PX = 8
LABEL_HEIGHT_PX = 20
MIN_HEIGHT_PX = 140
OUTLINE_RADIUS_PX = 6.0
OUTLINE_PEN_PX = 1.5
LED_INSET_FRACTION = 0.08  # padding inside an outline, of its smaller side
CELL_GAP_FRACTION = 0.15  # space between LED cells, of a cell's smaller side
ZONE_DOT_FRACTION = 0.4  # diameter of a zone device's dot, of the inner smaller side
HALF = 0.5
BACKGROUND = theme.WINDOW  # widget background (TEXT on it meets WCAG AA)
OUTLINE_FILL = theme.SURFACE
OUTLINE_PEN = theme.BORDER
UNLIT = theme.WINDOW  # an LED without a colour (no preset)
NAME_COLOUR = theme.TEXT
PLACEHOLDER_COLOUR = theme.TEXT_MUTED
NO_DEVICES_TEXT = "No devices to preview"
ACCESSIBLE_NAME = "LED preview"
NONE_TEXT = "none"
DESCRIPTION_TEXT = ("Preview of {count} device(s): {names}. Mode: {mode}. "
                    "Preset: {preset}.")
PRESET_TEXT = "{label} ({effect})"


@dataclass(frozen=True)
class PreviewDevice:
    """One device of the preview: serial, display name, type text and LED shape."""

    serial: str
    name: str
    type: str
    shape: DeviceShape


def nominal_size(device_type: str) -> tuple[float, float]:
    """Nominal ``(width_mm, height_mm)`` of a device type; unknown types get the default."""
    key = (device_type or "").strip().lower()
    return NOMINAL_SIZE_MM.get(key, NOMINAL_SIZE_MM[DEFAULT_TYPE])


class LedPreview(QWidget):
    """Draws devices left to right with their LEDs coloured by the current preset."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._devices: tuple[PreviewDevice, ...] = ()
        self._mode = MODE_SINGLE
        self._preset: Preset | None = None
        self._phase = 0.0
        self._frames: dict[str, Frame] = {}
        self._shown = False  # between showEvent and hideEvent
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self.setMinimumHeight(MIN_HEIGHT_PX)
        self.setAccessibleName(ACCESSIBLE_NAME)
        self._changed()

    # -- public API ----------------------------------------------------------

    def set_devices(self, devices: Iterable[PreviewDevice]) -> None:
        """Show ``devices``, left to right in the given (placement) order."""
        self._devices = tuple(devices)
        self._changed()

    def set_mode(self, mode: str) -> None:
        """``'single'`` (each device on its own) or ``'group'`` (one synced group)."""
        if mode not in MODE_LABELS:
            raise ValueError(f"unknown preview mode {mode!r}")
        self._mode = mode
        self._changed()

    def set_preset(self, preset: Preset | None) -> None:
        """Light the LEDs with ``preset`` (None leaves them unlit)."""
        self._preset = preset
        self._changed()

    def set_phase(self, phase: float) -> None:
        """Jump to ``phase`` (a fraction of one effect cycle) and repaint."""
        self._phase = phase % 1
        self._render()
        self.update()

    def devices(self) -> tuple[PreviewDevice, ...]:
        """The shown devices, in placement order."""
        return self._devices

    def mode(self) -> str:
        """The current mode, ``'single'`` or ``'group'``."""
        return self._mode

    def preset(self) -> Preset | None:
        """The previewed preset, or None."""
        return self._preset

    def is_running(self) -> bool:
        """True while the animation timer runs."""
        return self._timer.isActive()

    def colour_at(self, serial: str, row: int, col: int) -> RGB | None:
        """Colour of LED ``(row, col)`` of ``serial`` (a zone device has only (0, 0))."""
        frame = self._frames.get(serial)
        if frame is None or not 0 <= row < len(frame) or not 0 <= col < len(frame[row]):
            return None
        return frame[row][col]

    def device_rects(self) -> dict[str, QRectF]:
        """Outline of each device in widget pixels, keyed by serial in placement order."""
        return self._geometry()[0]

    # -- state ---------------------------------------------------------------

    def _changed(self) -> None:
        self._render()
        self._sync_timer()
        self.setAccessibleDescription(self._describe())
        self.update()

    def _render(self) -> None:
        """Recompute every LED colour with the animator's own maths."""
        self._frames = {}
        if self._preset is None or not self._devices:
            return
        shapes = [device.shape for device in self._devices]
        try:
            if self._mode == MODE_GROUP:
                self._frames = render_run(self._preset, group_layout(shapes), self._phase)
                return
            for shape in shapes:
                self._frames.update(render_run(self._preset, single_layout(shape), self._phase))
        except Exception:  # an odd unsaved preset must never break painting
            logger.warning("LED preview could not render the preset", exc_info=True)
            self._frames = {}

    def _sync_timer(self) -> None:
        animated = self._preset is not None and is_animated(self._preset)
        run = self._shown and animated and bool(self._devices)
        if run and not self._timer.isActive():
            self._timer.start()
        elif not run:
            self._timer.stop()

    def _tick(self) -> None:
        if self._preset is not None:
            self.set_phase(advance_phase(self._preset, self._phase, PREVIEW_FPS))

    def _describe(self) -> str:
        names = ", ".join(device.name for device in self._devices) or NONE_TEXT
        preset = NONE_TEXT
        if self._preset is not None:
            effect = EFFECT_LABELS.get(self._preset.effect, self._preset.effect)
            preset = PRESET_TEXT.format(label=self._preset.label, effect=effect)
        return DESCRIPTION_TEXT.format(count=len(self._devices), names=names,
                                       mode=MODE_LABELS[self._mode], preset=preset)

    def _geometry(self) -> tuple[dict[str, QRectF], float]:
        """Outlines (keeping NOMINAL_SIZE_MM proportions) and the mm-to-pixel scale."""
        sizes = [nominal_size(device.type) for device in self._devices]
        if not sizes:
            return {}, 0.0
        total_w = sum(width for width, _ in sizes) + GAP_MM * (len(sizes) - 1)
        total_h = max(height for _, height in sizes)
        avail_w = self.width() - 2 * MARGIN_PX
        avail_h = self.height() - 2 * MARGIN_PX - LABEL_HEIGHT_PX
        scale = max(0.0, min(avail_w / total_w, avail_h / total_h))
        left = (self.width() - total_w * scale) * HALF
        bottom = MARGIN_PX + (avail_h + total_h * scale) * HALF  # outlines share a baseline
        rects = {}
        for device, (width, height) in zip(self._devices, sizes):
            rects[device.serial] = QRectF(left, bottom - height * scale,
                                          width * scale, height * scale)
            left += (width + GAP_MM) * scale
        return rects, scale

    # -- events and painting -------------------------------------------------

    def showEvent(self, event: QShowEvent) -> None:
        """Start animating once visible."""
        super().showEvent(event)
        self._shown = True
        self._sync_timer()

    def hideEvent(self, event: QHideEvent) -> None:
        """Stop animating while hidden."""
        super().hideEvent(event)
        self._shown = False
        self._sync_timer()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw every device outline, its LEDs and its name (or a placeholder)."""
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.fillRect(self.rect(), QColor(BACKGROUND))
            rects, scale = self._geometry()
            if not rects:
                painter.setPen(QColor(PLACEHOLDER_COLOUR))
                painter.drawText(QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter,
                                 NO_DEVICES_TEXT)
                return
            for device in self._devices:
                self._paint_device(painter, device, rects[device.serial], GAP_MM * scale)
        finally:
            painter.end()

    def _paint_device(self, painter: QPainter, device: PreviewDevice, rect: QRectF,
                      gap_px: float) -> None:
        pen = QPen(QColor(OUTLINE_PEN))
        pen.setWidthF(OUTLINE_PEN_PX)
        painter.setPen(pen)
        painter.setBrush(QColor(OUTLINE_FILL))
        painter.drawRoundedRect(rect, OUTLINE_RADIUS_PX, OUTLINE_RADIUS_PX)
        inset = min(rect.width(), rect.height()) * LED_INSET_FRACTION
        inner = rect.adjusted(inset, inset, -inset, -inset)
        painter.setPen(Qt.PenStyle.NoPen)
        if device.shape.matrix:
            self._paint_matrix(painter, device, inner)
        else:
            self._paint_zone(painter, device, inner)
        self._paint_name(painter, device.name, rect, gap_px)

    def _paint_matrix(self, painter: QPainter, device: PreviewDevice, inner: QRectF) -> None:
        """One cell per LED on a uniform grid filling ``inner``."""
        rows, cols = device.shape.rows, device.shape.cols
        cell_w, cell_h = inner.width() / cols, inner.height() / rows
        gap = min(cell_w, cell_h) * CELL_GAP_FRACTION
        for row in range(rows):
            for col in range(cols):
                painter.setBrush(self._led_colour(device.serial, row, col))
                painter.drawRect(QRectF(inner.left() + col * cell_w + gap * HALF,
                                        inner.top() + row * cell_h + gap * HALF,
                                        cell_w - gap, cell_h - gap))

    def _paint_zone(self, painter: QPainter, device: PreviewDevice, inner: QRectF) -> None:
        """A zone-only device shows one colour: one dot in the middle."""
        diameter = min(inner.width(), inner.height()) * ZONE_DOT_FRACTION
        centre = inner.center()
        painter.setBrush(self._led_colour(device.serial, 0, 0))
        painter.drawEllipse(centre, diameter * HALF, diameter * HALF)

    def _paint_name(self, painter: QPainter, name: str, rect: QRectF, gap_px: float) -> None:
        """The device name centred under its outline, elided to its slot."""
        slot = QRectF(rect.left() - gap_px * HALF, rect.bottom(),
                      rect.width() + gap_px, LABEL_HEIGHT_PX)
        text = self.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight,
                                             int(slot.width()))
        painter.setPen(QColor(NAME_COLOUR))
        painter.drawText(slot, Qt.AlignmentFlag.AlignCenter, text)

    def _led_colour(self, serial: str, row: int, col: int) -> QColor:
        rgb = self.colour_at(serial, row, col)
        return QColor(*rgb) if rgb is not None else QColor(UNLIT)
