# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 RazerUI contributors
"""Lighting controls: zone, effect, effect parameters and brightness.

Backend calls that touch the device are submitted with
``worker.run_async(...)`` - looked up on the :mod:`razerui.ui.worker` module at
call time, so tests can monkeypatch ``worker.run_async`` to run synchronously.
"""

import logging
from functools import partial
from typing import Any, Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget,
)

from razerui.backend.devices import ZoneInfo, list_zones
from razerui.backend.lighting import (
    EFFECTS, PARAM_COLOUR1, PARAM_COLOUR2, PARAM_DIRECTION, PARAM_TIME, REACTIVE_LONG,
    REACTIVE_MED, REACTIVE_SHORT, WAVE_LEFT, WAVE_RIGHT, Effect, LightingError, apply_effect,
    get_brightness, set_brightness, supported_effects, supports_brightness,
)
from razerui.ui import worker
from razerui.ui.colour_button import ColourButton

logger = logging.getLogger(__name__)

DEFAULT_COLOUR1 = (0, 255, 0)
DEFAULT_COLOUR2 = (0, 0, 255)
SPEED_CHOICES = (("Short", REACTIVE_SHORT), ("Medium", REACTIVE_MED), ("Long", REACTIVE_LONG))
DIRECTION_CHOICES = (("Right", WAVE_RIGHT), ("Left", WAVE_LEFT))
BRIGHTNESS_SLIDER_MIN = 0
BRIGHTNESS_SLIDER_MAX = 100
BRIGHTNESS_PAGE_STEP = 10
ROW_ZONE = "zone"
ROW_EFFECT = "effect"
ROW_BRIGHTNESS = "brightness"
PARAM_ROWS = (PARAM_COLOUR1, PARAM_COLOUR2, PARAM_TIME, PARAM_DIRECTION)


def _choice_combo(choices: tuple[tuple[str, int], ...], parent: QWidget) -> QComboBox:
    combo = QComboBox(parent)
    for text, value in choices:
        combo.addItem(text, value)
    return combo


class LightingPanel(QWidget):
    """Choose a zone and effect for a device and apply it; ``status`` reports results."""

    status = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dev: Any = None
        self._zones: list[ZoneInfo] = []
        self._labels: dict[str, QLabel] = {}
        self._writing = False  # a device write from this panel is pending
        self._brightness_queued = False  # brightness changed while a write was pending
        self._build_widgets()
        self._build_layout()
        self._connect_signals()
        self._set_tab_order()
        self.set_device(None)

    # -- construction --------------------------------------------------------

    def _build_widgets(self) -> None:
        self.zone_combo = QComboBox(self)
        self.zone_combo.setAccessibleName("Lighting zone")
        self.effect_combo = QComboBox(self)
        self.effect_combo.setAccessibleName("Lighting effect")
        self.colour1_button = ColourButton("Primary colour", DEFAULT_COLOUR1, self)
        self.colour2_button = ColourButton("Secondary colour", DEFAULT_COLOUR2, self)
        self.speed_combo = _choice_combo(SPEED_CHOICES, self)
        self.speed_combo.setAccessibleName("Effect speed")
        self.direction_combo = _choice_combo(DIRECTION_CHOICES, self)
        self.direction_combo.setAccessibleName("Wave direction")
        self.brightness_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.brightness_slider.setRange(BRIGHTNESS_SLIDER_MIN, BRIGHTNESS_SLIDER_MAX)
        self.brightness_slider.setPageStep(BRIGHTNESS_PAGE_STEP)
        self.brightness_slider.setAccessibleName("Brightness")
        self.apply_button = QPushButton("&Apply", self)
        self._param_widgets: dict[str, QWidget] = {
            PARAM_COLOUR1: self.colour1_button,
            PARAM_COLOUR2: self.colour2_button,
            PARAM_TIME: self.speed_combo,
            PARAM_DIRECTION: self.direction_combo,
        }

    def _rows(self) -> tuple[tuple[str, str, QWidget], ...]:
        return (
            (ROW_ZONE, "&Zone:", self.zone_combo),
            (ROW_EFFECT, "&Effect:", self.effect_combo),
            (PARAM_COLOUR1, "&Primary colour:", self.colour1_button),
            (PARAM_COLOUR2, "&Secondary colour:", self.colour2_button),
            (PARAM_TIME, "Spee&d:", self.speed_combo),
            (PARAM_DIRECTION, "Di&rection:", self.direction_combo),
            (ROW_BRIGHTNESS, "&Brightness:", self.brightness_slider),
        )

    def _build_layout(self) -> None:
        form = QFormLayout()
        for key, text, widget in self._rows():
            label = QLabel(text, self)
            label.setBuddy(widget)
            form.addRow(label, widget)
            self._labels[key] = label
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.apply_button)
        outer = QVBoxLayout(self)
        outer.addLayout(form)
        outer.addLayout(buttons)
        outer.addStretch(1)

    def _connect_signals(self) -> None:
        self.zone_combo.currentIndexChanged.connect(self._on_zone_changed)
        self.effect_combo.currentIndexChanged.connect(self._on_effect_changed)
        # Drags apply once on release; keyboard steps and groove clicks apply at once.
        self.brightness_slider.valueChanged.connect(self._on_brightness_changed)
        self.brightness_slider.sliderReleased.connect(self._apply_brightness)
        self.apply_button.clicked.connect(self._on_apply)

    def _set_tab_order(self) -> None:
        chain = [widget for _key, _text, widget in self._rows()] + [self.apply_button]
        for first, second in zip(chain, chain[1:]):
            QWidget.setTabOrder(first, second)

    # -- state ---------------------------------------------------------------

    def set_device(self, dev: Any) -> None:
        """Show the zones and effects of ``dev`` (None clears the panel)."""
        self._dev = dev
        self._brightness_queued = False
        self._zones = list_zones(dev) if dev is not None else []
        self.zone_combo.blockSignals(True)
        self.zone_combo.clear()
        for zone in self._zones:
            self.zone_combo.addItem(zone.label, zone.key)
        self.zone_combo.blockSignals(False)
        self._on_zone_changed()

    def current_zone(self) -> ZoneInfo | None:
        """The selected zone, or None."""
        index = self.zone_combo.currentIndex()
        return self._zones[index] if 0 <= index < len(self._zones) else None

    def current_effect(self) -> Effect | None:
        """The selected effect, or None."""
        key = self.effect_combo.currentData()
        return EFFECTS.get(key) if key is not None else None

    def _on_zone_changed(self, _index: int = 0) -> None:
        zone = self.current_zone()
        effects = supported_effects(self._dev, zone) if zone is not None else []
        self.effect_combo.blockSignals(True)
        self.effect_combo.clear()
        for effect in effects:
            self.effect_combo.addItem(effect.label, effect.key)
        self.effect_combo.blockSignals(False)
        self.zone_combo.setEnabled(bool(self._zones))
        self._update_brightness(zone)
        self._on_effect_changed()

    def _on_effect_changed(self, _index: int = 0) -> None:
        effect = self.current_effect()
        params = effect.params if effect is not None else ()
        for name in PARAM_ROWS:
            visible = name in params
            self._param_widgets[name].setVisible(visible)
            self._labels[name].setVisible(visible)
        self.effect_combo.setEnabled(self.effect_combo.count() > 0)
        self.apply_button.setEnabled(effect is not None and not self._writing)

    def _update_brightness(self, zone: ZoneInfo | None) -> None:
        supported = zone is not None and supports_brightness(self._dev, zone)
        self.brightness_slider.setEnabled(supported)
        self._labels[ROW_BRIGHTNESS].setEnabled(supported)
        if not supported:
            return
        try:
            value = get_brightness(self._dev, zone)
        except LightingError as exc:
            self.status.emit(str(exc))
            return
        self.brightness_slider.blockSignals(True)  # loading must not write back
        self.brightness_slider.setValue(round(value))
        self.brightness_slider.blockSignals(False)

    def _collect_params(self) -> dict[str, Any]:
        return {
            PARAM_COLOUR1: self.colour1_button.colour(),
            PARAM_COLOUR2: self.colour2_button.colour(),
            PARAM_TIME: self.speed_combo.currentData(),
            PARAM_DIRECTION: self.direction_combo.currentData(),
        }

    # -- actions -------------------------------------------------------------

    def _set_writing(self, writing: bool) -> None:
        self._writing = writing
        self.apply_button.setEnabled(not writing and self.current_effect() is not None)

    def _submit(self, fn: Callable[[], Any], on_done: Callable[[Any], None]) -> None:
        self._set_writing(True)
        try:
            worker.run_async(fn, on_done, self._on_error)
        except Exception as exc:  # never let an exception escape a slot
            logger.exception("Could not start lighting task")
            self.status.emit(f"Lighting error: {exc}")
            self._set_writing(False)

    def _finish_write(self) -> None:
        """Re-enable writes and apply a brightness change made meanwhile."""
        self._set_writing(False)
        if self._brightness_queued:
            self._brightness_queued = False
            self._apply_brightness()

    def _on_apply(self) -> None:
        dev, zone, effect = self._dev, self.current_zone(), self.current_effect()
        if dev is None or zone is None or effect is None:
            self.status.emit("No lighting effect selected")
            return
        if self._writing:
            return
        params = self._collect_params()
        self._submit(partial(apply_effect, dev, zone, effect.key, params),
                     partial(self._on_apply_done, effect.label))

    @worker.ignore_deleted
    def _on_apply_done(self, label: str, ok: Any) -> None:
        if ok:
            self.status.emit(f"Applied {label}")
        else:
            self.status.emit(f"The device did not accept {label}")
        self._finish_write()

    def _on_brightness_changed(self, _value: int) -> None:
        if not self.brightness_slider.isSliderDown():  # drags apply on release
            self._apply_brightness()

    def _apply_brightness(self) -> None:
        dev, zone = self._dev, self.current_zone()
        if dev is None or zone is None or not self.brightness_slider.isEnabled():
            return
        if self._writing:
            self._brightness_queued = True
            return
        value = float(self.brightness_slider.value())
        self._submit(partial(set_brightness, dev, zone, value), self._on_brightness_done)

    @worker.ignore_deleted
    def _on_brightness_done(self, applied: Any) -> None:
        self.status.emit(f"Brightness set to {applied:.0f}%")
        self._finish_write()

    @worker.ignore_deleted
    def _on_error(self, message: str) -> None:
        logger.warning("Lighting action failed: %s", message)
        self.status.emit(f"Lighting error: {message}")
        self._finish_write()
