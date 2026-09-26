# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Preset editor: name, palette, effect, speed, direction and brightness of a preset.

The editor edits a copy of a :class:`Preset` and emits ``preset_changed`` with
the current preset on every user edit (a live preview listens to it). Built-in
presets are shown read-only; duplicate them to change them.
"""

import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSlider, QWidget,
)

from hueberry.backend.effects import (
    DIRECTION_FORWARD, DIRECTION_REVERSE, EFFECT_LABELS, MAX_LABEL_LENGTH, MAX_PALETTE,
    MAX_SPEED, MIN_PALETTE, MIN_SPEED, RGB, Preset,
)
from hueberry.ui.colour_button import ColourButton

__all__ = ["PresetEditor"]

logger = logging.getLogger(__name__)

SPEED_STEPS_PER_UNIT = 10  # slider steps per cycle/s (0.1 cycles/s resolution)
SPEED_PAGE_STEPS = SPEED_STEPS_PER_UNIT  # PgUp/PgDn move one cycle/s
BRIGHTNESS_PERCENT = 100  # slider range is 0..100 %
BRIGHTNESS_PAGE_STEP = 10
SPEED_FORMAT = "{speed:.1f} cycles/s"
BRIGHTNESS_FORMAT = "{percent} %"
COLOUR_ROLE = "Colour {number}"
NEW_COLOUR: RGB = (255, 255, 255)  # colour of a freshly added palette entry
DIRECTION_LABELS = {DIRECTION_FORWARD: "Forward", DIRECTION_REVERSE: "Reverse"}
READ_ONLY_TEXT = "Built-in presets are read-only; duplicate one to change it."


class PresetEditor(QWidget):
    """Form editing one preset; ``preset_changed(Preset)`` fires on every edit.

    :meth:`set_preset` loads a preset without emitting ``preset_changed``.
    """

    preset_changed = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._base: Preset | None = None  # key, width and builtin come from here
        self._loading = False  # set_preset() is filling the fields
        self.colour_buttons: list[ColourButton] = []
        self._build_widgets()
        self._build_layout()
        self._connect_signals()
        self._update_enabled()

    # -- construction --------------------------------------------------------

    def _build_widgets(self) -> None:
        self.label_edit = QLineEdit(self)
        self.label_edit.setMaxLength(MAX_LABEL_LENGTH)
        self.label_edit.setAccessibleName("Preset name")
        self.palette_row = QHBoxLayout()
        self.add_colour_button = QPushButton("Add co&lour", self)
        self.remove_colour_button = QPushButton("Remo&ve colour", self)
        self.effect_combo = QComboBox(self)
        self.effect_combo.setAccessibleName("Effect")
        for key, label in EFFECT_LABELS.items():
            self.effect_combo.addItem(label, key)
        self.speed_slider = self._slider(round(MAX_SPEED * SPEED_STEPS_PER_UNIT), SPEED_PAGE_STEPS)
        self.speed_slider.setMinimum(round(MIN_SPEED * SPEED_STEPS_PER_UNIT))
        self.speed_slider.setAccessibleName("Speed")
        self.speed_value = QLabel(self)
        self.direction_combo = QComboBox(self)
        self.direction_combo.setAccessibleName("Direction")
        for key, label in DIRECTION_LABELS.items():
            self.direction_combo.addItem(label, key)
        self.brightness_slider = self._slider(BRIGHTNESS_PERCENT, BRIGHTNESS_PAGE_STEP)
        self.brightness_slider.setAccessibleName("Brightness")
        self.brightness_value = QLabel(self)
        self.read_only_label = QLabel(READ_ONLY_TEXT, self)
        self.read_only_label.setWordWrap(True)

    def _slider(self, maximum: int, page_step: int) -> QSlider:
        slider = QSlider(Qt.Orientation.Horizontal, self)
        slider.setRange(0, maximum)
        slider.setPageStep(page_step)
        return slider

    def _build_layout(self) -> None:
        palette = QHBoxLayout()
        palette.addLayout(self.palette_row)
        palette.addWidget(self.add_colour_button)
        palette.addWidget(self.remove_colour_button)
        palette.addStretch(1)
        form = QFormLayout(self)
        form.addRow(self._buddy("&Name:", self.label_edit), self.label_edit)
        form.addRow(self._buddy("&Colours:", self.add_colour_button), palette)
        form.addRow(self._buddy("E&ffect:", self.effect_combo), self.effect_combo)
        form.addRow(self._buddy("S&peed:", self.speed_slider),
                    self._with_value(self.speed_slider, self.speed_value))
        form.addRow(self._buddy("Direct&ion:", self.direction_combo), self.direction_combo)
        form.addRow(self._buddy("&Brightness:", self.brightness_slider),
                    self._with_value(self.brightness_slider, self.brightness_value))
        form.addRow(self.read_only_label)

    def _buddy(self, text: str, widget: QWidget) -> QLabel:
        label = QLabel(text, self)
        label.setBuddy(widget)
        return label

    @staticmethod
    def _with_value(slider: QSlider, value: QLabel) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(slider, 1)
        row.addWidget(value)
        return row

    def _connect_signals(self) -> None:
        self.label_edit.textChanged.connect(self._on_edited)
        self.effect_combo.currentIndexChanged.connect(self._on_edited)
        self.direction_combo.currentIndexChanged.connect(self._on_edited)
        self.speed_slider.valueChanged.connect(self._on_edited)
        self.brightness_slider.valueChanged.connect(self._on_edited)
        self.add_colour_button.clicked.connect(self._add_colour)
        self.remove_colour_button.clicked.connect(self._remove_colour)

    # -- public API ----------------------------------------------------------

    def set_preset(self, preset: Preset | None) -> None:
        """Show ``preset`` (None clears and disables the form); never emits ``preset_changed``."""
        self._loading = True
        try:
            self._base = preset
            if preset is not None:
                self._fill(preset)
            else:
                self._set_palette(())
                self.label_edit.clear()
        finally:
            self._loading = False
        self._update_values()
        self._update_enabled()

    def preset(self) -> Preset | None:
        """The edited preset (not validated), or None when no preset is shown."""
        if self._base is None:
            return None
        return self._base.with_changes(
            label=self.label_edit.text(),
            effect=self.effect_combo.currentData(),
            palette=tuple(button.colour() for button in self.colour_buttons),
            speed=self.speed_slider.value() / SPEED_STEPS_PER_UNIT,
            direction=self.direction_combo.currentData(),
            brightness=self.brightness_slider.value() / BRIGHTNESS_PERCENT,
        )

    def is_read_only(self) -> bool:
        """True when a built-in (or no) preset is shown."""
        return self._base is None or self._base.builtin

    def first_widget(self) -> QWidget:
        """First widget of the editor's tab order."""
        return self.label_edit

    def last_widget(self) -> QWidget:
        """Last widget of the editor's tab order."""
        return self.brightness_slider

    # -- internals -----------------------------------------------------------

    def _fill(self, preset: Preset) -> None:
        self.label_edit.setText(preset.label)
        self._set_palette(preset.palette)
        self.effect_combo.setCurrentIndex(max(0, self.effect_combo.findData(preset.effect)))
        self.speed_slider.setValue(round(preset.speed * SPEED_STEPS_PER_UNIT))
        self.direction_combo.setCurrentIndex(
            max(0, self.direction_combo.findData(preset.direction)))
        self.brightness_slider.setValue(round(preset.brightness * BRIGHTNESS_PERCENT))

    def _set_palette(self, palette: tuple[RGB, ...]) -> None:
        for button in self.colour_buttons:
            self.palette_row.removeWidget(button)
            button.deleteLater()
        self.colour_buttons = []
        for colour in palette:
            self._append_button(colour)
        self._update_tab_order()

    def _append_button(self, colour: RGB) -> None:
        role = COLOUR_ROLE.format(number=len(self.colour_buttons) + 1)
        button = ColourButton(role, colour, self)
        button.colour_changed.connect(self._on_edited)
        self.colour_buttons.append(button)
        self.palette_row.addWidget(button)

    def _add_colour(self) -> None:
        if len(self.colour_buttons) >= MAX_PALETTE or self.is_read_only():
            return
        last = self.colour_buttons[-1].colour() if self.colour_buttons else NEW_COLOUR
        self._append_button(last)
        self._update_tab_order()
        self._update_enabled()
        self._on_edited()

    def _remove_colour(self) -> None:
        if len(self.colour_buttons) <= MIN_PALETTE or self.is_read_only():
            return
        button = self.colour_buttons.pop()
        self.palette_row.removeWidget(button)
        button.deleteLater()
        self._update_tab_order()
        self._update_enabled()
        self._on_edited()

    def _update_tab_order(self) -> None:
        chain = [self.label_edit, *self.colour_buttons, self.add_colour_button,
                 self.remove_colour_button, self.effect_combo, self.speed_slider,
                 self.direction_combo, self.brightness_slider]
        for first, second in zip(chain, chain[1:]):
            QWidget.setTabOrder(first, second)

    def _update_enabled(self) -> None:
        editable = not self.is_read_only()
        for widget in (self.label_edit, self.effect_combo, self.speed_slider,
                       self.direction_combo, self.brightness_slider, *self.colour_buttons):
            widget.setEnabled(editable)
        count = len(self.colour_buttons)
        self.add_colour_button.setEnabled(editable and count < MAX_PALETTE)
        self.remove_colour_button.setEnabled(editable and count > MIN_PALETTE)
        self.read_only_label.setVisible(self._base is not None and self._base.builtin)

    def _update_values(self) -> None:
        speed = self.speed_slider.value() / SPEED_STEPS_PER_UNIT
        self.speed_value.setText(SPEED_FORMAT.format(speed=speed))
        percent = self.brightness_slider.value()
        self.brightness_value.setText(BRIGHTNESS_FORMAT.format(percent=percent))

    def _on_edited(self, *_args: object) -> None:
        """Slot for every field: refresh the value labels and emit the preset."""
        self._update_values()
        if self._loading or self.is_read_only():
            return
        preset = self.preset()
        logger.debug("Preset %s edited", preset.key if preset else None)
        self.preset_changed.emit(preset)
