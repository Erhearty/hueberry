# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Frame building helpers of the advanced runtime (:mod:`hueberry.backend.advanced_runtime`).

Pure functions: nothing here touches a device, a lock or a thread.
"""

import random
from typing import Sequence

from hueberry.backend.advanced_presets import AdvancedPreset, DeviceProgram
from hueberry.backend.animator_targets import Target
from hueberry.backend.effects import RGB, Frame
from hueberry.backend.key_effect_render import BLACK, Cell, Press, press_lifetime, render_group
from hueberry.backend.key_effects import is_animated, uses_presses
from hueberry.backend.key_positions import STANDARD_COLS, STANDARD_ROWS, position_for

__all__ = ["animated", "frame", "press_cell", "preset_press_lifetime"]

NO_PRESS_LIFETIME = 0.0


def _group_presses(presses: Sequence[Press], leds: set[Cell]) -> list[Press]:
    """The presses a group reacts to: on one of its keys, or of unknown position."""
    return [press for press in presses if press[1] is None or press[1] in leds]


def frame(program: DeviceProgram | None, target: Target, t: float,
          presses: Sequence[Press], rng: random.Random) -> Frame:
    """A full ``rows x cols`` frame of ``program``; keys outside its groups are black."""
    rows: list[list[RGB]] = [[BLACK] * target.cols for _ in range(target.rows)]
    for group in program.groups if program is not None else ():
        leds = {(r, c) for r, c in group.leds if r < target.rows and c < target.cols}
        colours = render_group(group.effect, sorted(leds), t,
                               _group_presses(presses, leds), rng)
        for (row, col), colour in colours.items():
            rows[row][col] = colour
    return tuple(tuple(row) for row in rows)


def animated(preset: AdvancedPreset) -> bool:
    """True when a group of ``preset`` changes over time."""
    return any(is_animated(group.effect.effect)
               for program in preset.programs for group in program.groups)


def preset_press_lifetime(preset: AdvancedPreset) -> float:
    """How long a key press matters to ``preset`` (0 when no group uses presses)."""
    lifetimes = [press_lifetime(group.effect) for program in preset.programs
                 for group in program.groups if uses_presses(group.effect.effect)]
    return max(lifetimes, default=NO_PRESS_LIFETIME)


def press_cell(code: int, target: Target) -> tuple[bool, Cell | None]:
    """``(use, cell)`` for a key press on ``target``.

    A standard matrix places the key (unmapped keys are ignored); any other
    shape gets a press of unknown position.
    """
    if (target.rows, target.cols) != (STANDARD_ROWS, STANDARD_COLS):
        return True, None
    cell = position_for(code, target.rows, target.cols)
    return cell is not None, cell
