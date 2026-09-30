# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Where a pressed key sits in a keyboard's LED matrix.

Maps evdev key codes (the numbers of ``KEY_*`` in ``linux/input-event-codes.h``,
named in the comments so evdev need not be imported) to ``(row, col)`` cells
of the standard OpenRazer full-size keyboard matrix (6 rows x 22 columns, US
layout; column 0 holds macro keys on keyboards that have them). Other matrix
shapes have no table: :func:`position_for` returns None for them.
"""

__all__ = ["STANDARD_COLS", "STANDARD_POSITIONS", "STANDARD_ROWS", "position_for"]

STANDARD_ROWS = 6
STANDARD_COLS = 22

STANDARD_POSITIONS: dict[int, tuple[int, int]] = {
    # row 0: Esc, function keys, print/scroll/pause
    1: (0, 1),  # KEY_ESC
    59: (0, 3), 60: (0, 4), 61: (0, 5), 62: (0, 6),  # KEY_F1..KEY_F4
    63: (0, 7), 64: (0, 8), 65: (0, 9), 66: (0, 10),  # KEY_F5..KEY_F8
    67: (0, 11), 68: (0, 12), 87: (0, 13), 88: (0, 14),  # KEY_F9, KEY_F10, KEY_F11, KEY_F12
    99: (0, 15),  # KEY_SYSRQ
    70: (0, 16),  # KEY_SCROLLLOCK
    119: (0, 17),  # KEY_PAUSE
    # row 1: number row, navigation, keypad top
    41: (1, 1),  # KEY_GRAVE
    2: (1, 2), 3: (1, 3), 4: (1, 4), 5: (1, 5), 6: (1, 6),  # KEY_1..KEY_5
    7: (1, 7), 8: (1, 8), 9: (1, 9), 10: (1, 10), 11: (1, 11),  # KEY_6..KEY_0
    12: (1, 12),  # KEY_MINUS
    13: (1, 13),  # KEY_EQUAL
    14: (1, 14),  # KEY_BACKSPACE
    110: (1, 15),  # KEY_INSERT
    102: (1, 16),  # KEY_HOME
    104: (1, 17),  # KEY_PAGEUP
    69: (1, 18),  # KEY_NUMLOCK
    98: (1, 19),  # KEY_KPSLASH
    55: (1, 20),  # KEY_KPASTERISK
    74: (1, 21),  # KEY_KPMINUS
    # row 2: Tab, QWERTY row
    15: (2, 1),  # KEY_TAB
    16: (2, 2), 17: (2, 3), 18: (2, 4), 19: (2, 5), 20: (2, 6),  # KEY_Q, W, E, R, T
    21: (2, 7), 22: (2, 8), 23: (2, 9), 24: (2, 10), 25: (2, 11),  # KEY_Y, U, I, O, P
    26: (2, 12),  # KEY_LEFTBRACE
    27: (2, 13),  # KEY_RIGHTBRACE
    43: (2, 14),  # KEY_BACKSLASH
    111: (2, 15),  # KEY_DELETE
    107: (2, 16),  # KEY_END
    109: (2, 17),  # KEY_PAGEDOWN
    71: (2, 18), 72: (2, 19), 73: (2, 20),  # KEY_KP7, KEY_KP8, KEY_KP9
    78: (2, 21),  # KEY_KPPLUS
    # row 3: Caps Lock, home row
    58: (3, 1),  # KEY_CAPSLOCK
    30: (3, 2), 31: (3, 3), 32: (3, 4), 33: (3, 5), 34: (3, 6),  # KEY_A, S, D, F, G
    35: (3, 7), 36: (3, 8), 37: (3, 9), 38: (3, 10),  # KEY_H, J, K, L
    39: (3, 11),  # KEY_SEMICOLON
    40: (3, 12),  # KEY_APOSTROPHE
    28: (3, 14),  # KEY_ENTER
    75: (3, 18), 76: (3, 19), 77: (3, 20),  # KEY_KP4, KEY_KP5, KEY_KP6
    # row 4: shifts, bottom letter row, Up
    42: (4, 1),  # KEY_LEFTSHIFT
    86: (4, 2),  # KEY_102ND
    44: (4, 3), 45: (4, 4), 46: (4, 5), 47: (4, 6), 48: (4, 7),  # KEY_Z, X, C, V, B
    49: (4, 8), 50: (4, 9),  # KEY_N, KEY_M
    51: (4, 10),  # KEY_COMMA
    52: (4, 11),  # KEY_DOT
    53: (4, 12),  # KEY_SLASH
    54: (4, 14),  # KEY_RIGHTSHIFT
    103: (4, 16),  # KEY_UP
    79: (4, 18), 80: (4, 19), 81: (4, 20),  # KEY_KP1, KEY_KP2, KEY_KP3
    96: (4, 21),  # KEY_KPENTER
    # row 5: modifiers, Space, arrows, keypad bottom
    29: (5, 1),  # KEY_LEFTCTRL
    125: (5, 2),  # KEY_LEFTMETA
    56: (5, 3),  # KEY_LEFTALT
    57: (5, 7),  # KEY_SPACE
    100: (5, 11),  # KEY_RIGHTALT
    126: (5, 12),  # KEY_RIGHTMETA
    127: (5, 13),  # KEY_COMPOSE
    97: (5, 14),  # KEY_RIGHTCTRL
    105: (5, 15),  # KEY_LEFT
    108: (5, 16),  # KEY_DOWN
    106: (5, 17),  # KEY_RIGHT
    82: (5, 19),  # KEY_KP0
    83: (5, 20),  # KEY_KPDOT
}


def position_for(code: int, rows: int, cols: int) -> tuple[int, int] | None:
    """The ``(row, col)`` of evdev key ``code`` on a ``rows`` x ``cols`` matrix.

    None when the matrix is not the standard 6x22 shape or the key has no LED.
    """
    if (rows, cols) != (STANDARD_ROWS, STANDARD_COLS):
        return None
    return STANDARD_POSITIONS.get(code)
