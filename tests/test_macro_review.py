# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the recorded-steps review dialog."""

import pytest
from PyQt6.QtCore import Qt

from hueberry.macros import model
from hueberry.macros.model import DelayStep, KeyStep, WheelStep
from hueberry.ui.macro_review import ReviewDialog

STEPS = [
    KeyStep("KEY_A", model.ACTION_PRESS),
    KeyStep("BTN_LEFT", model.ACTION_PRESS),
    WheelStep(model.WHEEL_UP),
    DelayStep(20),
    KeyStep("KEY_B", model.ACTION_RELEASE),
]


@pytest.fixture
def review(qtbot):
    dialog = ReviewDialog(STEPS)
    qtbot.addWidget(dialog)
    return dialog


def _checked(dialog):
    return [dialog.list_widget.item(row).checkState() == Qt.CheckState.Checked
            for row in range(dialog.list_widget.count())]


def test_rows_show_describe_step_and_start_checked(review):
    texts = [review.list_widget.item(row).text() for row in range(review.list_widget.count())]
    assert texts == ["Press A", "Press Button Left", "Scroll up", "Wait 20 ms", "Release B"]
    assert review.steps() == STEPS


def test_all_checks_every_row(review):
    review.none_button.click()
    review.all_button.click()
    assert _checked(review) == [True] * len(STEPS)
    assert review.steps() == STEPS


def test_none_unchecks_every_row(review):
    review.none_button.click()
    assert _checked(review) == [False] * len(STEPS)
    assert review.steps() == []


def test_mouse_only_keeps_mouse_buttons_and_wheel(review):
    review.mouse_button.click()
    assert review.steps() == [STEPS[1], STEPS[2]]


def test_keyboard_only_keeps_keys_without_delays(review):
    review.keyboard_button.click()
    assert review.steps() == [STEPS[0], STEPS[4]]


def test_steps_keep_recording_order_after_manual_toggle(review):
    review.list_widget.item(1).setCheckState(Qt.CheckState.Unchecked)
    assert review.steps() == [STEPS[0], STEPS[2], STEPS[3], STEPS[4]]
