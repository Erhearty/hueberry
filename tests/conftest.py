# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Shared fixtures: fake, API-shaped ``openrazer.client`` and ``evdev`` packages.

The openrazer fake mirrors the public surface of the real openrazer client
library (DeviceManager, DaemonNotFound, constants, devices with ``fx`` /
``fx.misc``); the evdev fake (see ``fake_evdev.py``) mirrors python-evdev's
devices, uinput and ecodes. Tests never touch the real daemon, D-Bus, input
devices or /dev/uinput.
"""

import sys
import types

import pytest

from fake_evdev import FakeInputDevice, FakeUInput, InputEvent, UInputError, make_ecodes

FAKE_DAEMON_VERSION = "3.12.1-fake"
FAKE_CLIENT_VERSION = "3.12.1"
MISC_ZONE_NAMES = (
    "logo", "scroll_wheel", "left", "right",
    "backlight", "charging", "fast_charging", "fully_charged",
)
DEFAULT_BRIGHTNESS = 100.0
DEFAULT_MAX_DPI = 16000
DEFAULT_DPI = (800, 800)
DEFAULT_POLL_RATE = 1000
DEFAULT_POLL_RATES = [125, 500, 1000]
MATRIX_CAPABILITY = "lighting_led_matrix"
MATRIX_ROWS = 6
MATRIX_COLS = 22


class DaemonNotFound(Exception):
    """Fake of ``openrazer.client.DaemonNotFound``."""


def _make_constants() -> types.ModuleType:
    """Build a fake ``openrazer.client.constants`` mirroring real names."""
    constants = types.ModuleType("openrazer.client.constants")
    constants.WAVE_RIGHT = 0x01
    constants.WAVE_LEFT = 0x02
    constants.WHEEL_RIGHT = 0x01
    constants.WHEEL_LEFT = 0x02
    constants.REACTIVE_500MS = 0x01
    constants.REACTIVE_1000MS = 0x02
    constants.REACTIVE_1500MS = 0x03
    constants.REACTIVE_2000MS = 0x04
    constants.STARLIGHT_FAST = 0x01
    constants.STARLIGHT_NORMAL = 0x02
    constants.STARLIGHT_SLOW = 0x03
    constants.RIPPLE_REFRESH_RATE = 0.05
    return constants


class _Recorder:
    """Base for fake effect objects: records ``(method, args)`` tuples."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def _record(self, name: str, *args) -> None:
        self.calls.append((name, args))

    def none(self): self._record("none")
    def spectrum(self): self._record("spectrum")
    def wave(self, direction): self._record("wave", direction)
    def static(self, red, green, blue): self._record("static", red, green, blue)
    def reactive(self, red, green, blue, time): self._record("reactive", red, green, blue, time)
    def breath_single(self, red, green, blue): self._record("breath_single", red, green, blue)
    def breath_random(self): self._record("breath_random")

    def breath_dual(self, red, green, blue, red2, green2, blue2):
        self._record("breath_dual", red, green, blue, red2, green2, blue2)


class FakeAdvanced:
    """Fake of ``RazerAdvancedFX``: a per-key matrix with ``draw`` / ``restore``.

    ``matrix`` is a dict keyed by ``(row, col)`` so ``matrix[row, col] = rgb``
    works like the real ``Frame``; ``draws`` keeps a copy of every drawn frame.
    """

    def __init__(self, rows: int, cols: int) -> None:
        self.rows = rows
        self.cols = cols
        self.matrix: dict[tuple[int, int], tuple] = {}
        self.draws: list[dict] = []
        self.restore_calls = 0

    def draw(self) -> None:
        """Record a snapshot of the current matrix."""
        self.draws.append(dict(self.matrix))

    def restore(self) -> None:
        """Record a restore request."""
        self.restore_calls += 1


class FakeFx(_Recorder):
    """Fake of ``RazerFX`` (main device lighting)."""

    def __init__(self, capabilities: set[str]) -> None:
        super().__init__()
        self._capabilities = capabilities
        self.misc = types.SimpleNamespace(**{zone: None for zone in MISC_ZONE_NAMES})
        self.advanced: FakeAdvanced | None = None

    def has(self, capability: str) -> bool:
        """Mirror ``BaseRazerFX.has``: auto-prefixes ``lighting_``."""
        return "lighting_" + capability in self._capabilities

    def wheel(self, direction): self._record("wheel", direction)
    def ripple(self, red, green, blue, refreshrate=0.05): self._record("ripple", red, green, blue, refreshrate)
    def ripple_random(self, refreshrate=0.05): self._record("ripple_random", refreshrate)
    def starlight_single(self, red, green, blue, time): self._record("starlight_single", red, green, blue, time)
    def starlight_random(self, time): self._record("starlight_random", time)

    def breath_triple(self, red, green, blue, red2, green2, blue2, red3, green3, blue3):
        self._record("breath_triple", red, green, blue, red2, green2, blue2, red3, green3, blue3)

    def starlight_dual(self, red, green, blue, red2, green2, blue2, time):
        self._record("starlight_dual", red, green, blue, red2, green2, blue2, time)


class FakeLed(_Recorder):
    """Fake of ``SingleLed`` (a misc lighting zone)."""

    def __init__(self, led_name: str) -> None:
        super().__init__()
        self.led_name = led_name
        self.brightness = DEFAULT_BRIGHTNESS
        self.active = True

    def on(self): self._record("on")
    def blinking(self, red, green, blue): self._record("blinking", red, green, blue)
    def pulsate(self, red, green, blue): self._record("pulsate", red, green, blue)
    def breath_mono(self): self._record("breath_mono")


class FakeDevice:
    """Fake of ``RazerDevice`` / ``RazerMouse`` with plain attributes."""

    def __init__(self, name, device_type, serial, capabilities) -> None:
        self.name = name
        self.type = device_type
        self.serial = serial
        self.firmware_version = "v1.0"
        self.driver_version = "3.12.1"
        self.capabilities = {cap: True for cap in capabilities}
        self.brightness = DEFAULT_BRIGHTNESS
        self.fx = FakeFx(set(capabilities))
        self.dpi = DEFAULT_DPI
        self.max_dpi = DEFAULT_MAX_DPI
        self.available_dpi: list[int] = []
        self.poll_rate = DEFAULT_POLL_RATE
        self.supported_poll_rates = list(DEFAULT_POLL_RATES)

    def has(self, capability: str) -> bool:
        """Mirror ``RazerDevice.has`` backed by the capability set."""
        return self.capabilities.get(capability, False)


class FakeDeviceManager:
    """Fake of ``DeviceManager``; records settings and ``stop_daemon`` calls."""

    def __init__(self, devices: list) -> None:
        self.devices = list(devices)
        self.daemon_version = FAKE_DAEMON_VERSION
        self.version = FAKE_CLIENT_VERSION
        self.sync_effects = False
        self.turn_off_on_screensaver = False
        self.stop_calls = 0

    def stop_daemon(self) -> None:
        """Record a stop request."""
        self.stop_calls += 1


class ManagerFactory:
    """Callable standing in for ``openrazer.client.DeviceManager``.

    Configure ``devices`` / ``fail`` then call it like the real class; every
    construction is counted and kept in ``instances``.
    """

    def __init__(self) -> None:
        self.devices: list = []
        self.fail = False
        self.constructions = 0
        self.instances: list[FakeDeviceManager] = []

    def __call__(self) -> FakeDeviceManager:
        self.constructions += 1
        if self.fail:
            raise DaemonNotFound("Could not connect to daemon")
        manager = FakeDeviceManager(self.devices)
        self.instances.append(manager)
        return manager


def build_fake_openrazer() -> tuple[types.ModuleType, types.ModuleType, ManagerFactory]:
    """Create fresh fake ``openrazer`` and ``openrazer.client`` modules."""
    package = types.ModuleType("openrazer")
    package.__path__ = []
    client = types.ModuleType("openrazer.client")
    factory = ManagerFactory()
    client.DaemonNotFound = DaemonNotFound
    client.DeviceManager = factory
    client.constants = _make_constants()
    client.__version__ = FAKE_CLIENT_VERSION
    package.client = client
    return package, client, factory


@pytest.fixture(autouse=True)
def _fake_openrazer(monkeypatch):
    """Install the fake openrazer into ``sys.modules`` for every test."""
    package, client, factory = build_fake_openrazer()
    monkeypatch.setitem(sys.modules, "openrazer", package)
    monkeypatch.setitem(sys.modules, "openrazer.client", client)
    monkeypatch.setitem(sys.modules, "openrazer.client.constants", client.constants)
    return client, factory


def build_fake_evdev() -> types.ModuleType:
    """Create a fresh fake ``evdev`` module with its own device registry."""
    module = types.ModuleType("evdev")
    module.__path__ = []
    call_log: list = []
    device_cls = type("InputDevice", (FakeInputDevice,), {"registry": {}, "call_log": call_log})
    uinput_cls = type("UInput", (FakeUInput,),
                      {"instances": [], "call_log": call_log, "create_error": None})
    module.ecodes = make_ecodes()
    module.InputEvent = InputEvent
    module.InputDevice = device_cls
    module.UInput = uinput_cls
    module.UInputError = UInputError
    module.list_devices = lambda input_device_dir="/dev/input": sorted(device_cls.registry)
    module.call_log = call_log
    return module


@pytest.fixture(autouse=True)
def _fake_evdev(monkeypatch):
    """Install the fake evdev into ``sys.modules`` for every test."""
    module = build_fake_evdev()
    monkeypatch.setitem(sys.modules, "evdev", module)
    monkeypatch.setitem(sys.modules, "evdev.ecodes", module.ecodes)
    yield module
    for device in list(module.InputDevice.registry.values()):
        device.close()


@pytest.fixture
def fake_evdev(_fake_evdev):
    """The fake ``evdev`` module (register devices with ``InputDevice(path, name=...)``)."""
    return _fake_evdev


@pytest.fixture
def fake_client(_fake_openrazer):
    """The fake ``openrazer.client`` module."""
    return _fake_openrazer[0]


@pytest.fixture
def fake_manager_factory(_fake_openrazer):
    """The ``ManagerFactory`` installed as ``openrazer.client.DeviceManager``."""
    return _fake_openrazer[1]


@pytest.fixture
def make_device():
    """Factory fixture building ``FakeDevice`` objects.

    ``zones`` names misc zones (e.g. ``"logo"``, ``"scroll_wheel"``) to populate
    with ``FakeLed`` objects; others stay ``None`` like the real client. A
    device with ``lighting_led_matrix`` gets a ``FakeAdvanced`` matrix.
    """

    def _make(name="Razer Test Mouse", device_type="mouse", serial="PM0000000000001",
              capabilities=(), zones=()):
        device = FakeDevice(name, device_type, serial, capabilities)
        for zone in zones:
            setattr(device.fx.misc, zone, FakeLed(zone))
        if MATRIX_CAPABILITY in capabilities:
            device.fx.advanced = FakeAdvanced(MATRIX_ROWS, MATRIX_COLS)
        return device

    return _make
