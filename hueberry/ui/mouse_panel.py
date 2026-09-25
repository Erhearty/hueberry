# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Mouse controls: DPI (X/Y, optionally locked) and polling rate.

Device writes go through ``worker.run_async(...)`` looked up on the
:mod:`hueberry.ui.worker` module, so tests can monkeypatch it.
"""

import logging
from functools import partial
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QSpinBox,
    QVBoxLayout, QWidget,
)

from hueberry.backend.mouse import MIN_DPI, MouseControls, MouseError
from hueberry.ui import worker

logger = logging.getLogger(__name__)

DPI_SINGLE_STEP = 50
DPI_PAGE_STEP = 400
DPI_SUFFIX = " DPI"
POLL_RATE_FORMAT = "{rate} Hz"


def _apply_mouse(controls: MouseControls, x: int, y: int, rate: int | None) -> tuple[int, int]:
    """Worker function: set DPI, then the polling rate when given."""
    applied = controls.set_dpi(x, y)
    if rate is not None:
        controls.set_poll_rate(rate)
    return applied


def _dpi_spin(parent: QWidget, name: str) -> QSpinBox:
    spin = QSpinBox(parent)
    spin.setSingleStep(DPI_SINGLE_STEP)
    spin.setSuffix(DPI_SUFFIX)
    spin.setAccessibleName(name)
    return spin


class MousePanel(QWidget):
    """DPI and polling-rate editor; hidden for devices without adjustable DPI."""

    status = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controls: MouseControls | None = None
        self._writing = False  # a device write from this panel is pending
        self._build_widgets()
        self._build_layout()
        self._connect_signals()
        for first, second in zip(self._tab_chain(), self._tab_chain()[1:]):
            QWidget.setTabOrder(first, second)
        self.set_device(None)

    def _build_widgets(self) -> None:
        self.dpi_x_spin = _dpi_spin(self, "DPI X")
        self.dpi_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.dpi_slider.setSingleStep(DPI_SINGLE_STEP)
        self.dpi_slider.setPageStep(DPI_PAGE_STEP)
        self.dpi_slider.setAccessibleName("DPI X slider")
        self.lock_check = QCheckBox("&Lock X/Y", self)
        self.lock_check.setChecked(True)
        self.dpi_y_spin = _dpi_spin(self, "DPI Y")
        self.poll_combo = QComboBox(self)
        self.poll_combo.setAccessibleName("Polling rate")
        self.apply_button = QPushButton("Apply &mouse settings", self)

    def _build_layout(self) -> None:
        self.x_label = QLabel("DPI &X:", self)
        self.y_label = QLabel("DPI &Y:", self)
        self.poll_label = QLabel("&Polling rate:", self)
        for label, buddy in ((self.x_label, self.dpi_x_spin), (self.y_label, self.dpi_y_spin),
                             (self.poll_label, self.poll_combo)):
            label.setBuddy(buddy)
        x_row = QHBoxLayout()
        x_row.addWidget(self.dpi_x_spin)
        x_row.addWidget(self.dpi_slider, 1)
        form = QFormLayout()
        form.addRow(self.x_label, x_row)
        form.addRow("", self.lock_check)
        form.addRow(self.y_label, self.dpi_y_spin)
        form.addRow(self.poll_label, self.poll_combo)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.apply_button)
        outer = QVBoxLayout(self)
        outer.addLayout(form)
        outer.addLayout(buttons)
        outer.addStretch(1)

    def _connect_signals(self) -> None:
        self.dpi_x_spin.valueChanged.connect(self._on_x_changed)
        self.dpi_slider.valueChanged.connect(self.dpi_x_spin.setValue)
        self.lock_check.toggled.connect(self._on_lock_toggled)
        self.apply_button.clicked.connect(self._on_apply)

    def _tab_chain(self) -> list[QWidget]:
        return [self.dpi_x_spin, self.dpi_slider, self.lock_check, self.dpi_y_spin,
                self.poll_combo, self.apply_button]

    # -- state ---------------------------------------------------------------

    def set_device(self, dev: Any) -> None:
        """Load ``dev``'s settings; hide the panel for None or non-mice."""
        self._controls = None
        if dev is None:
            self.setVisible(False)
            return
        controls = MouseControls(dev)
        if not controls.supports_dpi():
            self.setVisible(False)
            return
        try:
            self._load(controls)
        except (MouseError, TypeError, ValueError) as exc:
            logger.warning("Could not read mouse settings: %s", exc)
            self.status.emit(f"Mouse error: {exc}")
            self.setVisible(False)
            return
        self._controls = controls
        self.setVisible(True)

    def _load(self, controls: MouseControls) -> None:
        max_dpi = max(controls.max_dpi(), MIN_DPI)
        dpi_x, dpi_y = controls.get_dpi()
        for widget in (self.dpi_x_spin, self.dpi_slider, self.dpi_y_spin):
            widget.setRange(MIN_DPI, max_dpi)
        locked = dpi_y in (dpi_x, 0)  # 0: fixed-DPI devices ignore Y
        self.lock_check.setChecked(locked)
        self.dpi_x_spin.setValue(dpi_x)
        self.dpi_slider.setValue(dpi_x)
        self.dpi_y_spin.setValue(dpi_x if locked else dpi_y)
        self._on_lock_toggled(locked)
        self._load_poll_rate(controls)

    def _load_poll_rate(self, controls: MouseControls) -> None:
        self.poll_combo.clear()
        supported = controls.supports_poll_rate()
        self.poll_combo.setEnabled(supported)
        self.poll_label.setEnabled(supported)
        if not supported:
            return
        for rate in controls.supported_poll_rates():
            self.poll_combo.addItem(POLL_RATE_FORMAT.format(rate=rate), rate)
        index = self.poll_combo.findData(controls.get_poll_rate())
        if index >= 0:
            self.poll_combo.setCurrentIndex(index)

    def _on_x_changed(self, value: int) -> None:
        self.dpi_slider.setValue(value)
        if self.lock_check.isChecked():
            self.dpi_y_spin.setValue(value)

    def _on_lock_toggled(self, locked: bool) -> None:
        self.dpi_y_spin.setEnabled(not locked)
        self.y_label.setEnabled(not locked)
        if locked:
            self.dpi_y_spin.setValue(self.dpi_x_spin.value())

    # -- actions -------------------------------------------------------------

    def _set_writing(self, writing: bool) -> None:
        self._writing = writing
        self.apply_button.setEnabled(not writing)

    def _on_apply(self) -> None:
        controls = self._controls
        if controls is None:
            self.status.emit("No mouse selected")
            return
        if self._writing:
            return
        dpi_x = self.dpi_x_spin.value()
        dpi_y = dpi_x if self.lock_check.isChecked() else self.dpi_y_spin.value()
        rate = self.poll_combo.currentData() if self.poll_combo.isEnabled() else None
        self._set_writing(True)
        try:
            worker.run_async(partial(_apply_mouse, controls, dpi_x, dpi_y, rate),
                             self._on_applied, self._on_error)
        except Exception as exc:  # never let an exception escape a slot
            logger.exception("Could not start mouse task")
            self.status.emit(f"Mouse error: {exc}")
            self._set_writing(False)

    @worker.ignore_deleted
    def _on_applied(self, applied: Any) -> None:
        self._set_writing(False)
        try:
            dpi_x, dpi_y = applied
        except (TypeError, ValueError):
            self.status.emit("Mouse settings applied")
            return
        self.status.emit(f"Mouse settings applied (DPI {dpi_x} x {dpi_y})")

    @worker.ignore_deleted
    def _on_error(self, message: str) -> None:
        self._set_writing(False)
        logger.warning("Mouse action failed: %s", message)
        self.status.emit(f"Mouse error: {message}")
