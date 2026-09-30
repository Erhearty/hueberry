# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the app-wide wheel guard."""

import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QComboBox, QSpinBox, QWidget

from hueberry.ui.wheel_guard import WheelGuard, install


def _wheel() -> QWheelEvent:
    return QWheelEvent(QPointF(1, 1), QPointF(1, 1), QPoint(0, 0), QPoint(0, 120),
                       Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                       Qt.ScrollPhase.NoScrollPhase, False)


@pytest.fixture
def installed_guard(qapp):
    """Install the guard on the app and remove it again after the test."""
    guard = install(qapp)
    yield guard
    qapp.removeEventFilter(guard)


def test_unfocused_spinbox_ignores_wheel(qapp):
    parent = QWidget()
    spin = QSpinBox(parent)
    spin.setValue(5)
    guard = WheelGuard()
    assert guard.eventFilter(spin, _wheel()) is True
    assert spin.value() == 5


def test_unfocused_combo_ignores_wheel(qapp):
    parent = QWidget()
    combo = QComboBox(parent)
    combo.addItems(["a", "b"])
    guard = WheelGuard()
    assert guard.eventFilter(combo, _wheel()) is True
    assert combo.currentIndex() == 0


def test_spinbox_line_edit_is_guarded(qapp):
    parent = QWidget()
    spin = QSpinBox(parent)
    assert WheelGuard().eventFilter(spin.lineEdit(), _wheel()) is True


def test_other_events_and_widgets_pass(qapp):
    guard = WheelGuard()
    assert guard.eventFilter(QWidget(), _wheel()) is False
    assert guard.eventFilter(QSpinBox(), QEvent(QEvent.Type.Show)) is False


def test_polished_fields_get_strong_focus(installed_guard, qtbot):
    spin = QSpinBox()
    combo = QComboBox()
    for widget in (spin, combo):
        qtbot.addWidget(widget)
        widget.ensurePolished()
        assert widget.focusPolicy() == Qt.FocusPolicy.StrongFocus


def test_existing_widget_converted_on_install(qapp, qtbot):
    spin = QSpinBox()
    qtbot.addWidget(spin)
    assert spin.focusPolicy() == Qt.FocusPolicy.WheelFocus
    guard = install(qapp)
    try:
        assert spin.focusPolicy() == Qt.FocusPolicy.StrongFocus
    finally:
        qapp.removeEventFilter(guard)


def test_no_focus_field_stays_no_focus(qapp, qtbot):
    spin = QSpinBox()
    qtbot.addWidget(spin)
    spin.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    guard = install(qapp)
    try:
        spin.ensurePolished()
        assert spin.focusPolicy() == Qt.FocusPolicy.NoFocus
    finally:
        qapp.removeEventFilter(guard)
