# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""What the lighting panel shows about the effect running on a device.

OpenRazer cannot read an effect back, so the panel preselects the effect
Hueberry last applied (:mod:`hueberry.backend.device_effects_store`) and says
what is running: a per-key effect of the advanced runtime, else the recorded
hardware effect. :class:`RunningRelay` refreshes the panel on the GUI thread
when the runtime changes or devices are claimed (both may happen on any thread).
"""

import logging
from typing import Any, Callable

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import QComboBox

from hueberry.backend import advanced_preset_store, advanced_runtime, device_effects_store
from hueberry.backend import lighting_state
from hueberry.backend.animator_targets import device_serial
from hueberry.backend.devices import ZoneInfo
from hueberry.backend.lighting import EFFECTS
from hueberry.ui.colour_button import RGB, ColourButton

__all__ = ["RunningRelay", "connect_panel", "record_for", "running_text", "select_data",
           "set_colour_quietly"]

logger = logging.getLogger(__name__)

RUNNING_TEXT = "Running: {label}"
PER_KEY_RUNNING_TEXT = "Running: {label} (Create effect)"

Record = tuple[str, dict[str, Any]]


def record_for(dev: Any, zone: ZoneInfo | None) -> Record | None:
    """The effect last recorded for ``zone`` of ``dev``, or None (never raises)."""
    if dev is None or zone is None:
        return None
    serial = device_serial(dev)
    return device_effects_store.load_record(serial, zone.key) if serial is not None else None


def select_data(combo: QComboBox, value: Any) -> bool:
    """Select the item holding ``value`` without emitting signals; False when absent."""
    index = combo.findData(value)
    if index < 0:
        return False
    combo.blockSignals(True)
    combo.setCurrentIndex(index)
    combo.blockSignals(False)
    return True


def set_colour_quietly(button: ColourButton, colour: RGB) -> None:
    """Show ``colour`` on ``button`` without emitting ``colour_changed``."""
    button.blockSignals(True)
    button.set_colour(tuple(colour))  # type: ignore[arg-type]
    button.blockSignals(False)


def _per_key_label(serial: str) -> str | None:
    """Label of the per-key preset shown on ``serial``, or None."""
    runtime = advanced_runtime.shared_runtime()
    key = runtime.active_key()
    if key is None or serial not in runtime.active_serials():
        return None
    presets, _error = advanced_preset_store.load()
    preset = advanced_preset_store.find_preset(key, presets)
    return preset.label if preset is not None else key


def running_text(dev: Any, zone: ZoneInfo | None) -> str | None:
    """``Running: …`` for ``dev`` and ``zone``, or None when nothing is known."""
    serial = device_serial(dev) if dev is not None else None
    if serial is None:
        return None
    try:
        label = _per_key_label(serial)
    except Exception:  # the recorded effect is still worth showing
        logger.exception("Could not read the per-key effect of %s", serial)
        label = None
    if label is not None:
        return PER_KEY_RUNNING_TEXT.format(label=label)
    record = record_for(dev, zone)
    effect = EFFECTS.get(record[0]) if record is not None else None
    return RUNNING_TEXT.format(label=effect.label) if effect is not None else None


class RunningRelay(QObject):
    """Hands runtime changes and claims (any thread) to ``refresh`` on the GUI thread."""

    changed = pyqtSignal()

    def __init__(self, refresh: Callable[[], None], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.changed.connect(refresh, Qt.ConnectionType.QueuedConnection)

    def notify(self, *_args: Any) -> None:
        """Change or claim listener: ask for a refresh (never raises)."""
        try:
            self.changed.emit()
        except RuntimeError:  # the panel is gone
            return


def connect_panel(panel: Any) -> RunningRelay:
    """Refresh ``panel``'s running label on runtime changes and device claims."""
    relay = RunningRelay(panel.refresh_running, panel)
    try:
        advanced_runtime.shared_runtime().add_change_listener(relay.notify)
        lighting_state.shared_lighting_state().add_claim_listener(relay.notify)
    except Exception:  # the panel still works; the label refreshes on selection
        logger.exception("Could not watch the running effect")
    return relay
