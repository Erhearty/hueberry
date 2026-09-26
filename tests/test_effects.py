# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the pure preset model, effect maths and LED layouts."""

from pathlib import Path

import pytest

from hueberry.backend import effects, led_layout, presets
from hueberry.backend.effects import Preset, PresetError
from hueberry.backend.led_layout import DeviceShape, group_layout, single_layout

ROWS = 6
COLS = 22
FPS = 60
FRAMES = 200  # enough frames to wrap the Erheart cycle several times
SAMPLE_PHASES = (0.0, 0.04, 0.2, 0.37, 0.5, 0.8, 0.96)
RED = (255, 0, 0)
BLUE = (0, 0, 255)
PURE_FILES = ("effects.py", "led_layout.py")

# -- the original Erheart maths, captured verbatim before the refactor --------
OLD_PALETTE = ((0xC0, 0x76, 0xFF), (0xB8, 0x6C, 0xEA), (0xFF, 0x3A, 0x82),
               (0xB8, 0x6C, 0xEA), (0xC0, 0x76, 0xFF))
OLD_WAVE_WIDTH = 1.0
OLD_WAVE_SPEED = 0.04
OLD_BRIGHTNESS = 1.0


def _old_palette_colour_at(pos):
    count = len(OLD_PALETTE)
    return OLD_PALETTE[int((pos % 1) * count) % count]


def _old_grid_position(row, col, rows, cols):
    return (row / max(rows - 1, 1) + col / max(cols - 1, 1)) / 2


def _old_wave_brightness(row, col, rows, cols, offset):
    pos = _old_grid_position(row, col, rows, cols)
    distance = abs(pos - offset % 1)
    distance = min(distance, 1 - distance)
    return max(0.0, 1 - distance / OLD_WAVE_WIDTH) ** 2


def _old_scaled(colour, brightness):
    red, green, blue = colour
    return (int(red * brightness * OLD_BRIGHTNESS), int(green * brightness * OLD_BRIGHTNESS),
            int(blue * brightness * OLD_BRIGHTNESS))


def _old_matrix_colour(row, col, rows, cols, offset):
    pos = _old_grid_position(row, col, rows, cols)
    base = _old_palette_colour_at((pos + offset) % 1)
    return _old_scaled(base, _old_wave_brightness(row, col, rows, cols, offset))


def _old_zone_colour(offset):
    return _old_scaled(_old_palette_colour_at(offset), _old_wave_brightness(1, 1, 2, 2, offset))


def _old_offsets(count):
    offset, out = 0.0, []
    for _ in range(count):
        out.append(offset)
        offset = (offset + OLD_WAVE_SPEED) % 1
    return out


def _new_phases(count):
    phase, out = 0.0, []
    for _ in range(count):
        out.append(phase)
        phase = effects.advance_phase(presets.ERHEART, phase, FPS)
    return out


# -- Erheart byte identity ------------------------------------------------------

@pytest.mark.parametrize("phase", SAMPLE_PHASES)
def test_erheart_matrix_matches_old_maths(phase):
    layout = single_layout(DeviceShape.of_matrix("KBD", ROWS, COLS))
    frame = effects.render_run(presets.ERHEART, layout, phase)["KBD"]
    for row in range(ROWS):
        for col in range(COLS):
            assert frame[row][col] == _old_matrix_colour(row, col, ROWS, COLS, phase)
            assert frame[row][col] == presets.matrix_colour(row, col, ROWS, COLS, phase)


def test_erheart_phase_steps_match_old_offsets():
    assert _new_phases(FRAMES) == _old_offsets(FRAMES)
    assert effects.phase_step(presets.ERHEART, FPS) == OLD_WAVE_SPEED


def test_erheart_zone_device_is_corner_of_2x2():
    layout = single_layout(DeviceShape.of_zones("MOUSE"))
    for offset in _old_offsets(FRAMES):
        ((colour,),) = effects.render_run(presets.ERHEART, layout, offset)["MOUSE"]
        assert colour == _old_zone_colour(offset) == presets.zone_colour(offset)


# -- model ----------------------------------------------------------------------

def _preset(**changes):
    base = Preset(key="mine", label="Mine", effect=effects.EFFECT_WAVE, palette=(RED, BLUE),
                  speed=1.0)
    return base.with_changes(**changes)


@pytest.mark.parametrize("changes", [
    {"key": ""}, {"key": "Bad Key"}, {"label": " "}, {"label": "x" * 65},
    {"effect": "sparkle"}, {"palette": ()}, {"palette": (RED,) * 17}, {"palette": ((256, 0, 0),)},
    {"palette": ((1, 2),)}, {"speed": -0.1}, {"speed": 11}, {"speed": True}, {"speed": False},
    {"direction": 0}, {"direction": 1}, {"direction": -1}, {"direction": "backward"},
    {"brightness": -0.1}, {"brightness": 1.5}, {"width": 0}, {"width": 2},
])
def test_validation_errors(changes):
    with pytest.raises(PresetError):
        _preset(**changes).validate()


def test_limits_and_zero_speed_are_valid():
    assert (effects.MAX_PALETTE, effects.MAX_LABEL_LENGTH) == (16, 64)
    _preset(label="x" * 64, palette=(RED,) * 16).validate()
    frozen = _preset(speed=0)
    frozen.validate()
    assert effects.advance_phase(frozen, 0.3, FPS) == pytest.approx(0.3)


@pytest.mark.parametrize("direction", [effects.DIRECTION_FORWARD, effects.DIRECTION_REVERSE])
def test_direction_strings_round_trip(direction):
    preset = _preset(direction=direction)
    data = preset.to_dict()
    assert data["direction"] == direction
    assert Preset.from_dict(data).direction == direction
    assert (effects.DIRECTION_FORWARD, effects.DIRECTION_REVERSE) == ("forward", "reverse")


def test_dict_round_trip():
    preset = _preset(direction=effects.DIRECTION_REVERSE, brightness=0.5, width=0.4)
    data = preset.to_dict()
    assert data["palette"] == ["#ff0000", "#0000ff"]
    assert "builtin" not in data
    assert Preset.from_dict(data) == preset


@pytest.mark.parametrize("data", [
    [], {"key": "a"}, {**_preset().to_dict(), "palette": "red"},
    {**_preset().to_dict(), "palette": ["#zzzzzz"]}, {**_preset().to_dict(), "speed": "fast"},
])
def test_from_dict_rejects_invalid(data):
    with pytest.raises(PresetError):
        Preset.from_dict(data)


def test_trailing_newline_is_rejected():
    with pytest.raises(PresetError):
        effects.hex_to_rgb("#ff0000\n")
    with pytest.raises(PresetError):
        _preset(key="calm\n").validate()
    assert effects.hex_to_rgb("#ff0000") == RED
    _preset(key="calm").validate()


# -- effect types ----------------------------------------------------------------

def test_wave_crest_is_full_brightness():
    preset = _preset(palette=(RED,))
    assert effects.led_colour(preset, 0.3, 0.3) == RED
    assert effects.led_colour(preset, 0.8, 0.3) == (int(255 * 0.5 ** 2), 0, 0)


def test_breathe_fades_in_and_out():
    preset = _preset(effect=effects.EFFECT_BREATHE, palette=(RED,))
    assert effects.led_colour(preset, 0.1, 0.0) == (0, 0, 0)
    assert effects.led_colour(preset, 0.9, 0.5) == RED


def test_cycle_steps_through_palette_everywhere():
    preset = _preset(effect=effects.EFFECT_CYCLE)
    assert effects.led_colour(preset, 0.0, 0.1) == effects.led_colour(preset, 0.9, 0.1) == RED
    assert effects.led_colour(preset, 0.0, 0.6) == BLUE


def test_static_is_first_palette_colour_and_not_animated():
    preset = _preset(effect=effects.EFFECT_STATIC, brightness=0.5)
    layout = single_layout(DeviceShape.of_matrix("KBD", ROWS, COLS))
    half_red = (int(255 * 0.5), 0, 0)
    for phase in SAMPLE_PHASES:
        frame = effects.render_run(preset, layout, phase)["KBD"]
        assert {colour for row in frame for colour in row} == {half_red}
    assert not effects.is_animated(preset)
    assert effects.is_animated(_preset())


def test_per_key_steps_palette_without_fall_off():
    preset = _preset(effect=effects.EFFECT_PER_KEY)
    assert effects.led_colour(preset, 0.1, 0.0) == RED
    assert effects.led_colour(preset, 0.9, 0.0) == BLUE
    assert effects.led_colour(preset, 0.1, 0.5) == BLUE  # scrolls with the phase
    layout = single_layout(DeviceShape.of_matrix("KBD", ROWS, COLS))
    frame = effects.render_run(preset, layout, 0.3)["KBD"]
    assert {colour for row in frame for colour in row} == {RED, BLUE}  # full brightness
    assert effects.is_animated(preset)


def _rotation_colours(preset, phases):
    layout = single_layout(DeviceShape.of_matrix("KBD", ROWS, COLS))
    return [effects.render_run(preset, layout, phase)["KBD"][0][0] for phase in phases]


def test_rotation_spins_with_phase_and_reverse_runs_opposite():
    palette = (RED, (0, 255, 0), BLUE, (255, 255, 0))
    forward = _preset(effect=effects.EFFECT_ROTATION, palette=palette, speed=6.0)
    reverse = forward.with_changes(direction=effects.DIRECTION_REVERSE)
    phases, phase = [], 0.0
    for _ in range(4):
        phases.append(phase)
        phase = effects.advance_phase(forward, phase, FPS)
    back, phase = [], 0.0
    for _ in range(4):
        back.append(phase)
        phase = effects.advance_phase(reverse, phase, FPS)
    spin = [palette.index(colour) for colour in _rotation_colours(forward, phases)]
    back_spin = [palette.index(colour) for colour in _rotation_colours(reverse, back)]
    assert spin == sorted(spin) and spin[-1] > spin[0]  # moves forward through the palette
    assert back_spin == sorted(back_spin, reverse=True) and back_spin[-1] < back_spin[0]
    layout = single_layout(DeviceShape.of_matrix("KBD", ROWS, COLS))
    frame = effects.render_run(forward, layout, 0.0)["KBD"]
    assert frame[0][0] != frame[ROWS - 1][COLS - 1]  # opposite sides of the centre differ


def test_grid_angle_goes_around_the_centre():
    layout = single_layout(DeviceShape.of_matrix("KBD", 3, 3))
    (placement,) = layout.placements
    assert effects.grid_angle(layout, placement, 1, 2) == pytest.approx(0.0)
    assert effects.grid_angle(layout, placement, 2, 1) == pytest.approx(0.25)
    assert effects.grid_angle(layout, placement, 1, 0) == pytest.approx(0.5)
    assert effects.grid_angle(layout, placement, 0, 1) == pytest.approx(0.75)


def test_direction_sign():
    forward = _preset(speed=6.0)
    backward = forward.with_changes(direction=effects.DIRECTION_REVERSE)
    assert effects.advance_phase(forward, 0.5, FPS) == pytest.approx(0.6)
    assert effects.advance_phase(backward, 0.5, FPS) == pytest.approx(0.4)
    assert effects.advance_phase(backward, 0.0, FPS) == pytest.approx(0.9)


def test_brightness_scales_every_channel():
    preset = _preset(effect=effects.EFFECT_CYCLE, palette=((200, 100, 50),), brightness=0.5)
    assert effects.led_colour(preset, 0.0, 0.0) == (100, 50, 25)


# -- layouts ----------------------------------------------------------------------

def test_group_layout_orders_side_by_side_without_overlap():
    shapes = [DeviceShape.of_matrix("KBD", ROWS, COLS), DeviceShape.of_zones("MOUSE"),
              DeviceShape.of_matrix("PAD", 1, 4)]
    layout = group_layout(shapes)
    assert layout.serials() == ("KBD", "MOUSE", "PAD")
    assert (layout.rows, layout.cols) == (ROWS, COLS + led_layout.ZONE_COLS + 4)
    spans = [(p.col_offset, p.col_offset + p.shape.cols) for p in layout.placements]
    assert spans == [(0, COLS), (COLS, COLS + 2), (COLS + 2, COLS + 6)]
    assert all(end <= start for (_s, end), (start, _e) in zip(spans, spans[1:]))


def test_group_render_gives_each_device_its_own_frame():
    layout = group_layout([DeviceShape.of_matrix("KBD", ROWS, COLS), DeviceShape.of_zones("M")])
    frames = effects.render_run(presets.ERHEART, layout, 0.3)
    assert len(frames["KBD"]) == ROWS and len(frames["KBD"][0]) == COLS
    assert len(frames["M"]) == 1 and len(frames["M"][0]) == 1


@pytest.mark.parametrize("shapes", [[], [DeviceShape.of_zones("A"), DeviceShape.of_zones("A")]])
def test_group_layout_rejects_empty_or_duplicates(shapes):
    with pytest.raises(ValueError):
        group_layout(shapes)


def test_matrix_shape_must_be_at_least_1x1():
    with pytest.raises(ValueError):
        DeviceShape.of_matrix("KBD", 0, COLS)


def test_effect_modules_are_pure():
    backend = Path(effects.__file__).parent
    for name in PURE_FILES:
        text = (backend / name).read_text(encoding="utf-8")
        for forbidden in ("openrazer", "PyQt6"):
            assert f"import {forbidden}" not in text
            assert f"from {forbidden}" not in text
