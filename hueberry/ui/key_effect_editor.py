# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Edit one :class:`KeyEffect`: its type, speed, brightness, colours and extras.

Only the parameters the chosen effect uses are shown: angle (wave), width
(wave, ripple), density (starlight), fade (reactive, ripple); spectrum has
no colours and static no speed. ``effect_changed(KeyEffect)`` is emitted on
every user edit, never by :meth:`KeyEffectEditor.set_effect`.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QDial, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QSlider,
    QSpinBox, QWidget,
)

from hueberry.backend import key_effects as ke
from hueberry.backend.key_effects import KeyEffect
from hueberry.ui.colour_button import ColourButton

__all__ = ["KeyEffectEditor"]

RGB = tuple[int, int, int]
SPEED_SCALE = 10  # slider steps per cycle/second
PERCENT = 100  # slider steps for 0..1 values
ANGLE_MAX = 359
FADE_STEP = 0.1
FADE_DECIMALS = 1
NEW_COLOUR: RGB = (255, 255, 255)
FIELD_SPEED = "speed"
FIELD_COLOURS = "colours"
FIELD_ANGLE = "angle"
FIELD_WIDTH = "width"
FIELD_DENSITY = "density"
FIELD_FADE = "fade"
FIELDS_FOR = {
    ke.EFFECT_STATIC: {FIELD_COLOURS},
    ke.EFFECT_WAVE: {FIELD_SPEED, FIELD_COLOURS, FIELD_ANGLE, FIELD_WIDTH},
    ke.EFFECT_BREATHING: {FIELD_SPEED, FIELD_COLOURS},
    ke.EFFECT_SPECTRUM: {FIELD_SPEED},
    ke.EFFECT_REACTIVE: {FIELD_COLOURS, FIELD_FADE},
    ke.EFFECT_RIPPLE: {FIELD_SPEED, FIELD_COLOURS, FIELD_WIDTH, FIELD_FADE},
    ke.EFFECT_STARLIGHT: {FIELD_COLOURS, FIELD_DENSITY},
}
COLOUR_ROLE = "Colour {index}"


def _slider(name: str, low: int, high: int) -> QSlider:
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(low, high)
    slider.setAccessibleName(name)
    return slider


class KeyEffectEditor(QWidget):
    """Form editing one key group's effect."""

    effect_changed = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._base = KeyEffect()
        self._loading = False
        self.colour_buttons: list[ColourButton] = []
        self._form = QFormLayout(self)
        self._labels: dict[str, QLabel] = {}
        self._rows: dict[str, QWidget] = {}
        self._build()
        self.set_effect(KeyEffect())

    # -- construction ------------------------------------------------------------

    def _build(self) -> None:
        self.effect_combo = QComboBox()
        self.effect_combo.setAccessibleName("Effect")
        for key, label in ke.EFFECT_LABELS.items():
            self.effect_combo.addItem(label, key)
        self._add_row("effect", "&Effect:", self.effect_combo)
        self.speed_slider = _slider("Speed", int(ke.MIN_SPEED * SPEED_SCALE),
                                    int(ke.MAX_SPEED * SPEED_SCALE))
        self._add_row(FIELD_SPEED, "&Speed:", self.speed_slider)
        self.brightness_slider = _slider("Brightness", 0, PERCENT)
        self._add_row("brightness", "&Brightness:", self.brightness_slider)
        self._add_row(FIELD_COLOURS, "&Colours:", self._build_colours())
        self._add_row(FIELD_ANGLE, "&Angle:", self._build_angle())
        self.width_slider = _slider("Width", int(ke.MIN_WIDTH * PERCENT), PERCENT)
        self._add_row(FIELD_WIDTH, "&Width:", self.width_slider)
        self.density_slider = _slider("Density", 0, PERCENT)
        self._add_row(FIELD_DENSITY, "&Density:", self.density_slider)
        self.fade_spin = QDoubleSpinBox()
        self.fade_spin.setRange(ke.MIN_FADE, ke.MAX_FADE)
        self.fade_spin.setSingleStep(FADE_STEP)
        self.fade_spin.setDecimals(FADE_DECIMALS)
        self.fade_spin.setSuffix(" s")
        self.fade_spin.setAccessibleName("Fade time")
        self._add_row(FIELD_FADE, "&Fade:", self.fade_spin)
        self._connect()

    def _add_row(self, field: str, text: str, widget: QWidget) -> None:
        label = QLabel(text)
        label.setBuddy(widget)
        self._form.addRow(label, widget)
        self._labels[field], self._rows[field] = label, widget

    def _build_colours(self) -> QWidget:
        box = QWidget()
        self._colour_layout = QHBoxLayout(box)
        self._colour_layout.setContentsMargins(0, 0, 0, 0)
        self.add_colour_button = QPushButton("+")
        self.add_colour_button.setAccessibleName("Add colour")
        self.add_colour_button.setToolTip("Add a colour")
        self.remove_colour_button = QPushButton("\u2212")
        self.remove_colour_button.setAccessibleName("Remove last colour")
        self.remove_colour_button.setToolTip("Remove the last colour")
        self._colour_layout.addWidget(self.add_colour_button)
        self._colour_layout.addWidget(self.remove_colour_button)
        return box

    def _build_angle(self) -> QWidget:
        box = QWidget()
        layout = QHBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        self.angle_dial = QDial()
        self.angle_dial.setRange(0, ANGLE_MAX)
        self.angle_dial.setWrapping(True)
        self.angle_dial.setAccessibleName("Wave angle dial")
        self.angle_spin = QSpinBox()
        self.angle_spin.setRange(0, ANGLE_MAX)
        self.angle_spin.setSuffix("\u00b0")
        self.angle_spin.setAccessibleName("Wave angle")
        layout.addWidget(self.angle_dial)
        layout.addWidget(self.angle_spin)
        return box

    def _connect(self) -> None:
        self.effect_combo.currentIndexChanged.connect(self._on_effect_type)
        for slider in (self.speed_slider, self.brightness_slider, self.width_slider,
                       self.density_slider):
            slider.valueChanged.connect(self._emit)
        self.fade_spin.valueChanged.connect(self._emit)
        self.angle_dial.valueChanged.connect(self.angle_spin.setValue)
        self.angle_spin.valueChanged.connect(self.angle_dial.setValue)
        self.angle_spin.valueChanged.connect(self._emit)
        self.add_colour_button.clicked.connect(self._add_colour)
        self.remove_colour_button.clicked.connect(self._remove_colour)

    # -- public API --------------------------------------------------------------

    def set_effect(self, effect: KeyEffect) -> None:
        """Show ``effect`` in the form (no ``effect_changed``)."""
        self._loading = True
        try:
            self._base = effect
            self.effect_combo.setCurrentIndex(max(self.effect_combo.findData(effect.effect), 0))
            self.speed_slider.setValue(round(effect.speed * SPEED_SCALE))
            self.brightness_slider.setValue(round(effect.brightness * PERCENT))
            self.width_slider.setValue(round(effect.width * PERCENT))
            self.density_slider.setValue(round(effect.density * PERCENT))
            self.fade_spin.setValue(effect.fade)
            self.angle_spin.setValue(round(effect.angle) % (ANGLE_MAX + 1))
            self._set_colours(effect.palette)
        finally:
            self._loading = False
        self._update_visibility()

    def effect(self) -> KeyEffect:
        """The effect as edited."""
        return self._base.with_changes(
            effect=self.effect_combo.currentData(),
            palette=tuple(button.colour() for button in self.colour_buttons),
            speed=self.speed_slider.value() / SPEED_SCALE,
            brightness=self.brightness_slider.value() / PERCENT,
            angle=float(self.angle_spin.value()),
            width=self.width_slider.value() / PERCENT,
            density=self.density_slider.value() / PERCENT,
            fade=round(self.fade_spin.value(), FADE_DECIMALS))

    def field_visible(self, field: str) -> bool:
        """True when ``field`` (e.g. ``"angle"``) is shown for the current effect."""
        return not self._rows[field].isHidden()

    # -- internals ---------------------------------------------------------------

    def _set_colours(self, palette: tuple[RGB, ...]) -> None:
        for button in self.colour_buttons:
            self._colour_layout.removeWidget(button)
            button.deleteLater()
        self.colour_buttons = []
        for colour in palette:
            self._append_colour(colour)
        self._update_colour_buttons()

    def _append_colour(self, colour: RGB) -> None:
        button = ColourButton(COLOUR_ROLE.format(index=len(self.colour_buttons) + 1), colour)
        button.colour_changed.connect(self._emit)
        self._colour_layout.insertWidget(len(self.colour_buttons), button)
        self.colour_buttons.append(button)

    def _add_colour(self) -> None:
        if len(self.colour_buttons) >= ke.MAX_PALETTE:
            return
        self._append_colour(NEW_COLOUR)
        self._update_colour_buttons()
        self._emit()

    def _remove_colour(self) -> None:
        if len(self.colour_buttons) <= ke.MIN_PALETTE:
            return
        button = self.colour_buttons.pop()
        self._colour_layout.removeWidget(button)
        button.deleteLater()
        self._update_colour_buttons()
        self._emit()

    def _update_colour_buttons(self) -> None:
        count = len(self.colour_buttons)
        self.add_colour_button.setEnabled(count < ke.MAX_PALETTE)
        self.remove_colour_button.setEnabled(count > ke.MIN_PALETTE)

    def _on_effect_type(self) -> None:
        self._update_visibility()
        self._emit()

    def _update_visibility(self) -> None:
        shown = FIELDS_FOR.get(self.effect_combo.currentData(), set())
        for field in (FIELD_SPEED, FIELD_COLOURS, FIELD_ANGLE, FIELD_WIDTH, FIELD_DENSITY,
                      FIELD_FADE):
            visible = field in shown
            self._rows[field].setVisible(visible)
            self._labels[field].setVisible(visible)

    def _emit(self, *_args: object) -> None:
        if not self._loading:
            self.effect_changed.emit(self.effect())
