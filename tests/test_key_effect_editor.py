# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the key effect editor."""

import pytest

from hueberry.backend import key_effects as ke
from hueberry.backend.key_effects import KeyEffect
from hueberry.ui.key_effect_editor import KeyEffectEditor

WAVE = KeyEffect(effect=ke.EFFECT_WAVE, palette=((255, 0, 0), (0, 0, 255)), speed=2.5,
                 brightness=0.8, angle=90.0, width=0.3, density=0.2, fade=1.5)


@pytest.fixture
def editor(qtbot):
    widget = KeyEffectEditor()
    qtbot.addWidget(widget)
    return widget


def _choose(editor, effect):
    editor.effect_combo.setCurrentIndex(editor.effect_combo.findData(effect))


@pytest.mark.parametrize("effect, shown", [
    (ke.EFFECT_STATIC, {"colours"}),
    (ke.EFFECT_WAVE, {"speed", "colours", "angle", "width"}),
    (ke.EFFECT_BREATHING, {"speed", "colours"}),
    (ke.EFFECT_SPECTRUM, {"speed"}),
    (ke.EFFECT_REACTIVE, {"colours", "fade"}),
    (ke.EFFECT_RIPPLE, {"speed", "colours", "width", "fade"}),
    (ke.EFFECT_STARLIGHT, {"colours", "density"}),
])
def test_visibility_per_effect(editor, effect, shown):
    _choose(editor, effect)
    fields = {"speed", "colours", "angle", "width", "density", "fade"}
    assert {field for field in fields if editor.field_visible(field)} == shown


def test_round_trip(editor):
    editor.set_effect(WAVE)
    assert editor.effect() == WAVE
    assert len(editor.colour_buttons) == 2
    assert editor.angle_dial.value() == 90


def test_set_effect_is_silent_and_edits_emit(qtbot, editor):
    with qtbot.assertNotEmitted(editor.effect_changed):
        editor.set_effect(WAVE)
    with qtbot.waitSignal(editor.effect_changed) as blocker:
        editor.speed_slider.setValue(40)
    assert blocker.args[0].speed == 4.0
    with qtbot.waitSignal(editor.effect_changed) as blocker:
        editor.angle_dial.setValue(45)
    assert blocker.args[0].angle == 45.0


def test_add_and_remove_colours(qtbot, editor):
    editor.set_effect(KeyEffect())
    assert not editor.remove_colour_button.isEnabled()
    with qtbot.waitSignal(editor.effect_changed) as blocker:
        editor.add_colour_button.click()
    assert blocker.args[0].palette == ((0, 255, 0), (255, 255, 255))
    for _ in range(ke.MAX_PALETTE):
        editor.add_colour_button.click()
    assert len(editor.colour_buttons) == ke.MAX_PALETTE
    assert not editor.add_colour_button.isEnabled()
    editor.remove_colour_button.click()
    assert len(editor.effect().palette) == ke.MAX_PALETTE - 1
    editor.colour_buttons[0].set_colour((1, 2, 3))
    assert editor.effect().palette[0] == (1, 2, 3)


def test_widgets_have_accessible_names(editor):
    for widget in (editor.effect_combo, editor.speed_slider, editor.brightness_slider,
                   editor.angle_spin, editor.angle_dial, editor.width_slider,
                   editor.density_slider, editor.fade_spin, editor.add_colour_button,
                   editor.remove_colour_button):
        assert widget.accessibleName()
    editor.effect().validate()
