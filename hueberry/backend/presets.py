# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""The Erheart lighting preset: a pink/purple diagonal wave.

Pure maths only - nothing here imports openrazer or PyQt6 - so the animator
(:mod:`hueberry.backend.animator`) and the tests share one definition of the
colours. Colours are ``(r, g, b)`` tuples of 0-255 integers; positions and
offsets are fractions of one wave cycle (only ``value % 1`` matters).
"""

PRESET_KEY = "erheart"
PRESET_LABEL = "Erheart"

PALETTE_HEX = ("#c076ff", "#b86cea", "#ff3a82", "#b86cea", "#c076ff")
WAVE_WIDTH = 1.0  # distance (in cycles) over which the wave fades to black
WAVE_SPEED = 0.04  # cycles advanced per frame
BRIGHTNESS = 1.0  # overall scale applied to every colour
FPS = 60  # animation frames per second

#: Devices that do not animate but get one fixed static colour.
SERIAL_OVERRIDES: dict[str, tuple[int, int, int]] = {"ST2433V02000015": (255, 58, 130)}

# A zone device is treated as the far corner of a 2x2 grid.
ZONE_ROW = 1
ZONE_COL = 1
ZONE_ROWS = 2
ZONE_COLS = 2

HEX_PREFIX = "#"
HEX_BASE = 16
HEX_CHANNEL_WIDTH = 2
CHANNELS = 3

#: D-Bus error names meaning the device object is gone (unplugged / daemon restarted).
STALE_ERROR_MARKERS = ("UnknownMethod", "UnknownObject", "ServiceUnknown", "NoReply")
#: Error texts meaning the device node is not ready yet (permissions / missing file).
NOT_READY_ERROR_MARKERS = ("Errno 13", "Errno 2")


def hex_to_rgb(text: str) -> tuple[int, int, int]:
    """Convert ``'#rrggbb'`` to an ``(r, g, b)`` tuple."""
    digits = text.removeprefix(HEX_PREFIX)
    channels = [int(digits[index:index + HEX_CHANNEL_WIDTH], HEX_BASE)
                for index in range(0, CHANNELS * HEX_CHANNEL_WIDTH, HEX_CHANNEL_WIDTH)]
    return (channels[0], channels[1], channels[2])


#: :data:`PALETTE_HEX` as ``(r, g, b)`` tuples.
PALETTE: tuple[tuple[int, int, int], ...] = tuple(hex_to_rgb(text) for text in PALETTE_HEX)


def palette_colour_at(pos: float) -> tuple[int, int, int]:
    """Palette colour at cycle position ``pos`` (stepwise, no blending)."""
    count = len(PALETTE)
    return PALETTE[int((pos % 1) * count) % count]


def grid_position(row: int, col: int, rows: int, cols: int) -> float:
    """Diagonal position of a key in 0..1: the mean of its row and column fractions."""
    return (row / max(rows - 1, 1) + col / max(cols - 1, 1)) / 2


def wave_brightness(row: int, col: int, rows: int, cols: int, offset: float) -> float:
    """Brightness (0..1) of a key when the wave crest is at ``offset``.

    The distance to the crest wraps around the cycle and the fall-off is
    squared, so keys at the crest are full brightness.
    """
    pos = grid_position(row, col, rows, cols)
    distance = abs(pos - offset % 1)
    distance = min(distance, 1 - distance)
    return max(0.0, 1 - distance / WAVE_WIDTH) ** 2


def _scaled(colour: tuple[int, int, int], brightness: float) -> tuple[int, int, int]:
    red, green, blue = colour
    return (int(red * brightness * BRIGHTNESS), int(green * brightness * BRIGHTNESS),
            int(blue * brightness * BRIGHTNESS))


def matrix_colour(row: int, col: int, rows: int, cols: int,
                  offset: float) -> tuple[int, int, int]:
    """Colour of key ``(row, col)`` of a ``rows`` x ``cols`` matrix at ``offset``."""
    pos = grid_position(row, col, rows, cols)
    base = palette_colour_at((pos + offset) % 1)
    return _scaled(base, wave_brightness(row, col, rows, cols, offset))


def zone_colour(offset: float) -> tuple[int, int, int]:
    """Single colour for a device without a key matrix at ``offset``."""
    brightness = wave_brightness(ZONE_ROW, ZONE_COL, ZONE_ROWS, ZONE_COLS, offset)
    return _scaled(palette_colour_at(offset), brightness)


def next_offset(offset: float) -> float:
    """Offset of the next frame: advances :data:`WAVE_SPEED` cycles per frame."""
    return (offset + WAVE_SPEED) % 1


def is_stale_error(exc: BaseException) -> bool:
    """True when ``exc`` says the device's D-Bus object no longer exists."""
    text = str(exc)
    return any(marker in text for marker in STALE_ERROR_MARKERS)


def is_not_ready_error(exc: BaseException) -> bool:
    """True when ``exc`` says the device is not ready yet (retry next frame)."""
    if isinstance(exc, (PermissionError, FileNotFoundError)):
        return True
    text = str(exc)
    return any(marker in text for marker in NOT_READY_ERROR_MARKERS)
