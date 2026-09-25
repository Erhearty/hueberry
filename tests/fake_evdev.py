# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""A fake, API-shaped ``evdev`` package (python-evdev) for tests.

Mirrors the parts of python-evdev the macro engine uses: ``ecodes``,
``InputEvent``, ``InputDevice``, ``UInput``, ``UInputError`` and
``list_devices``. Devices are registered by path (constructing
``InputDevice(path, name=...)`` with keyword configuration registers it);
opening ``InputDevice(path)`` without configuration returns the registered
instance, like reopening the same node. Grabs, reads and uinput writes are
scriptable and recorded so tests never touch real devices.
"""

import errno
import os
import types
from collections import namedtuple

EV_SYN = 0x00
EV_KEY = 0x01
EV_REL = 0x02
EV_MSC = 0x04
EV_FF = 0x15
SYN_REPORT = 0
REL_X = 0x00
MSC_SCAN = 0x04
DEFAULT_BUSTYPE = 0x03
DEFAULT_VERSION = 0x0111
USEC_PER_SEC = 1_000_000
PIPE_DRAIN_BYTES = 4096
WAKE_BYTE = b"\0"

KEY_CODES = {
    "KEY_RESERVED": 0, "KEY_ESC": 1, "KEY_1": 2, "KEY_2": 3, "KEY_3": 4, "KEY_4": 5,
    "KEY_5": 6, "KEY_6": 7, "KEY_7": 8, "KEY_8": 9, "KEY_9": 10, "KEY_0": 11,
    "KEY_Q": 16, "KEY_W": 17, "KEY_E": 18, "KEY_R": 19, "KEY_T": 20, "KEY_Y": 21,
    "KEY_U": 22, "KEY_I": 23, "KEY_O": 24, "KEY_P": 25, "KEY_ENTER": 28,
    "KEY_LEFTCTRL": 29, "KEY_A": 30, "KEY_S": 31, "KEY_D": 32, "KEY_F": 33,
    "KEY_G": 34, "KEY_H": 35, "KEY_J": 36, "KEY_K": 37, "KEY_L": 38,
    "KEY_LEFTSHIFT": 42, "KEY_Z": 44, "KEY_X": 45, "KEY_C": 46, "KEY_V": 47,
    "KEY_B": 48, "KEY_N": 49, "KEY_M": 50, "KEY_LEFTALT": 56, "KEY_SPACE": 57,
    "KEY_F1": 59, "KEY_F2": 60, "KEY_MACRO1": 0x290, "KEY_MAX": 0x2FF, "KEY_CNT": 0x300,
}
BTN_CODES = {
    "BTN_MISC": 0x100, "BTN_0": 0x100, "BTN_MOUSE": 0x110, "BTN_LEFT": 0x110,
    "BTN_RIGHT": 0x111, "BTN_MIDDLE": 0x112, "BTN_SIDE": 0x113, "BTN_EXTRA": 0x114,
}
OTHER_CODES = {
    "EV_SYN": EV_SYN, "EV_KEY": EV_KEY, "EV_REL": EV_REL, "EV_MSC": EV_MSC, "EV_FF": EV_FF,
    "SYN_REPORT": SYN_REPORT, "REL_X": REL_X, "MSC_SCAN": MSC_SCAN,
}

DeviceInfo = namedtuple("DeviceInfo", "bustype vendor product version")


def _by_code(names_to_codes: dict) -> dict:
    """Invert name->code like python-evdev: aliases become a sorted list."""
    grouped: dict = {}
    for name, code in sorted(names_to_codes.items()):
        grouped.setdefault(code, []).append(name)
    return {code: names[0] if len(names) == 1 else names for code, names in grouped.items()}


def make_ecodes() -> types.ModuleType:
    """Build a fake ``evdev.ecodes`` module with real code values."""
    ecodes = types.ModuleType("evdev.ecodes")
    all_codes = {**KEY_CODES, **BTN_CODES, **OTHER_CODES}
    for name, code in all_codes.items():
        setattr(ecodes, name, code)
    ecodes.ecodes = dict(all_codes)
    ecodes.KEY = _by_code(KEY_CODES)
    ecodes.BTN = _by_code(BTN_CODES)
    ecodes.keys = {**ecodes.KEY, **ecodes.BTN}
    ecodes.EV = _by_code({n: c for n, c in OTHER_CODES.items() if n.startswith("EV_")})
    return ecodes


class UInputError(Exception):
    """Fake of ``evdev.UInputError``."""


class InputEvent:
    """Fake of ``evdev.InputEvent``."""

    def __init__(self, sec, usec, type, code, value) -> None:  # noqa: A002 - mirrors evdev
        self.sec = sec
        self.usec = usec
        self.type = type
        self.code = code
        self.value = value

    def timestamp(self) -> float:
        """Seconds as a float, like the real event."""
        return self.sec + self.usec / USEC_PER_SEC

    def __repr__(self) -> str:
        return f"InputEvent({self.sec}, {self.usec}, {self.type}, {self.code}, {self.value})"


def make_event(etype: int, code: int, value: int, t: float = 0.0) -> InputEvent:
    """Build an ``InputEvent`` from a float timestamp."""
    sec = int(t)
    return InputEvent(sec, round((t - sec) * USEC_PER_SEC), etype, code, value)


class FakeInputDevice:
    """Fake of ``evdev.InputDevice`` with scriptable grab/read and a wake pipe."""

    registry: dict = {}
    call_log: list = []

    def __new__(cls, path, **config):
        if config:
            return super().__new__(cls)
        existing = cls.registry.get(path)
        if existing is None:
            raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), path)
        if existing.open_error is not None:
            raise OSError(existing.open_error, os.strerror(existing.open_error), path)
        existing.closed = False
        existing.open_count += 1
        return existing

    def __init__(self, path, *, name="Fake Device", vendor=0x1532, product=0x0001,
                 keys=(), phys="usb-fake/input0", uniq="") -> None:
        if getattr(self, "_ready", False):
            return
        self._ready = True
        self.path = path
        self.name = name
        self.info = DeviceInfo(DEFAULT_BUSTYPE, vendor, product, DEFAULT_VERSION)
        self.phys = phys
        self.uniq = uniq
        self.keys = list(keys)
        self.grab_error: int | None = None
        self.open_error: int | None = None
        self.read_error: BaseException | None = None
        self.held_keys: list = []
        self.grabbed = False
        self.grab_calls = 0
        self.ungrab_calls = 0
        self.open_count = 1
        self.closed = False
        self._queue: list = []
        self._pipe: tuple[int, int] | None = None
        type(self).registry[path] = self

    def capabilities(self, verbose=False, absinfo=True) -> dict:
        """Event types to codes; EV_KEY only when the device has keys."""
        caps = {EV_SYN: [SYN_REPORT]}
        if self.keys:
            caps[EV_KEY] = list(self.keys)
        return caps

    def grab(self) -> None:
        """Grab, or raise the scripted ``grab_error`` errno as OSError."""
        self.call_log.append(("grab", self.path))
        if self.grab_error is not None:
            raise OSError(self.grab_error, os.strerror(self.grab_error))
        self.grabbed = True
        self.grab_calls += 1

    def active_keys(self, verbose=False) -> list:
        """Codes of keys/buttons currently held (scripted via ``held_keys``)."""
        return list(self.held_keys)

    def ungrab(self) -> None:
        """Release a grab."""
        self.call_log.append(("ungrab", self.path))
        self.grabbed = False
        self.ungrab_calls += 1

    def queue_events(self, *events) -> None:
        """Script events for the next ``read()`` and wake any selector."""
        self._queue.extend(events)
        if self._pipe is not None:
            os.write(self._pipe[1], WAKE_BYTE)

    def fileno(self) -> int:
        """A pipe read end that is readable while events are queued."""
        if self._pipe is None:
            read_fd, write_fd = os.pipe()
            os.set_blocking(read_fd, False)
            self._pipe = (read_fd, write_fd)
            if self._queue:
                os.write(write_fd, WAKE_BYTE)
        return self._pipe[0]

    def _drain(self) -> None:
        if self._pipe is None:
            return
        try:
            while os.read(self._pipe[0], PIPE_DRAIN_BYTES):
                pass
        except BlockingIOError:
            pass

    def read(self):
        """Return queued events; BlockingIOError when none, like a non-blocking fd."""
        if self.read_error is not None:
            raise self.read_error
        if not self._queue:
            raise BlockingIOError(errno.EAGAIN, os.strerror(errno.EAGAIN))
        events, self._queue = self._queue, []
        self._drain()
        return iter(events)

    def read_one(self):
        """Return one queued event, or None."""
        return self._queue.pop(0) if self._queue else None

    def close(self) -> None:
        """Mark closed and release the wake pipe."""
        self.closed = True
        if self._pipe is not None:
            for fd in self._pipe:
                os.close(fd)
            self._pipe = None


class FakeUInput:
    """Fake of ``evdev.UInput`` recording every write, syn and close."""

    instances: list = []
    call_log: list = []
    create_error: BaseException | None = None

    def __init__(self, events=None, name="py-evdev-uinput", vendor=0x1, product=0x1,
                 version=0x1, bustype=DEFAULT_BUSTYPE, devnode="/dev/uinput",
                 phys="py-evdev-uinput", input_props=None, max_effects=None) -> None:
        if type(self).create_error is not None:
            raise type(self).create_error
        self.events = events
        self.name = name
        self.writes: list[tuple[int, int, int]] = []
        self.write_error: BaseException | None = None
        self.closed = False
        self.close_calls = 0
        self.call_log.append(("uinput", name))
        self.instances.append(self)

    @classmethod
    def from_device(cls, *devices, filtered_types=(EV_SYN, EV_FF), **kwargs):
        """Clone the capabilities of ``devices`` like the real classmethod."""
        events: dict = {}
        for device in devices:
            for etype, codes in device.capabilities().items():
                if etype not in filtered_types:
                    events.setdefault(etype, []).extend(codes)
        return cls(events=events, **kwargs)

    def write(self, etype, code, value) -> None:
        """Record one event, or raise the scripted ``write_error``."""
        if self.write_error is not None:
            raise self.write_error
        self.writes.append((etype, code, value))

    def write_event(self, event) -> None:
        """Record an ``InputEvent``."""
        self.write(event.type, event.code, event.value)

    def syn(self) -> None:
        """Record a SYN_REPORT."""
        self.write(EV_SYN, SYN_REPORT, 0)

    def close(self) -> None:
        """Mark closed."""
        self.closed = True
        self.close_calls += 1
