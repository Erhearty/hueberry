# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Placeholder page shown when the daemon is unreachable or no device is found."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

TITLE_TEXT = "<b>No Razer devices available</b>"
HINT_TEXT = (
    "Make sure the OpenRazer daemon and python3-openrazer are installed, "
    "that your user is in the plugdev group, and that the daemon is running."
)
START_TEXT = "&Start daemon"
RETRY_TEXT = "R&etry"


class EmptyStatePanel(QWidget):
    """Shows why nothing can be displayed and offers Start daemon / Retry.

    The buttons only emit ``start_requested`` / ``retry_requested``; the owner
    decides what to run.
    """

    start_requested = pyqtSignal()
    retry_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._busy = False
        self._can_start = True
        self.title_label = QLabel(TITLE_TEXT, self)
        self.message_label = QLabel("", self)
        self.message_label.setWordWrap(True)
        self.message_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.message_label.setAccessibleName("Error")
        self.hint_label = QLabel(HINT_TEXT, self)
        self.hint_label.setWordWrap(True)
        self.start_button = QPushButton(START_TEXT, self)
        self.retry_button = QPushButton(RETRY_TEXT, self)
        self.start_button.clicked.connect(self.start_requested)
        self.retry_button.clicked.connect(self.retry_requested)
        self._build_layout()
        QWidget.setTabOrder(self.start_button, self.retry_button)

    def _build_layout(self) -> None:
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.retry_button)
        buttons.addStretch(1)
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        for label in (self.title_label, self.message_label, self.hint_label):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            outer.addWidget(label)
        outer.addLayout(buttons)
        outer.addStretch(1)

    def set_message(self, text: str) -> None:
        """Show ``text`` (typically the service's last error)."""
        self.message_label.setText(text)

    def set_busy(self, busy: bool) -> None:
        """Disable the buttons while an action is running."""
        self._busy = busy
        self._update_buttons()

    def set_can_start(self, can_start: bool) -> None:
        """Offer 'Start daemon' only when it can help (i.e. not already connected)."""
        self._can_start = can_start
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.start_button.setEnabled(self._can_start and not self._busy)
        self.retry_button.setEnabled(not self._busy)
