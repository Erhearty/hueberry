# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""An opened input device as the engine loop tracks it, plus its remapper."""

from dataclasses import dataclass
from typing import Any


@dataclass
class DeviceHandle:
    """An opened device plus the remapper using it (if any)."""

    identity: str
    name: str
    device: Any
    remapper: Any = None

    @property
    def remapping(self) -> bool:
        """True while the remapper is active or still waiting to grab."""
        return self.remapper is not None and (self.remapper.active or self.remapper.pending_grab)

    @property
    def pending_grab(self) -> bool:
        """True while the remapper defers its grab until no key is held."""
        return self.remapper is not None and self.remapper.pending_grab

    def retry_grab(self) -> None:
        """Attempt a deferred grab; a no-op when none is pending."""
        if self.pending_grab:
            self.remapper.try_grab()
