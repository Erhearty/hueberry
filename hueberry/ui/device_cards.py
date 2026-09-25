# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Home screen: a scrollable grid of checkable, keyboard-activatable device cards."""

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QFocusEvent, QKeyEvent, QResizeEvent
from PyQt6.QtWidgets import (
    QButtonGroup, QGridLayout, QScrollArea, QStyle, QToolButton, QVBoxLayout, QWidget,
)

from hueberry.backend.devices import DeviceInfo
from hueberry.ui.device_icons import icon_for_type

CARD_OBJECT_NAME = "deviceCard"
SCROLL_OBJECT_NAME = "deviceGridScroll"
SERIAL_PROPERTY = "serial"
GRID_ACCESSIBLE_NAME = "Devices"
CARD_WIDTH = 180
CARD_HEIGHT = 150
CARD_TEXT_WIDTH = 156  # CARD_WIDTH minus the card's padding and border
CARD_ICON_SIZE = 64
GRID_SPACING = 12
MIN_COLUMNS = 1
MAX_COLUMNS = 6
FRAME_SIDES = 2
ACTIVATE_KEYS = (Qt.Key.Key_Return, Qt.Key.Key_Enter)
ARROW_KEYS = (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down)
STEP_BACK = -1
STEP_FORWARD = 1


def columns_for_width(width: int) -> int:
    """Number of card columns that fit in ``width`` pixels, clamped to the limits."""
    fitting = (width + GRID_SPACING) // (CARD_WIDTH + GRID_SPACING)
    return max(MIN_COLUMNS, min(MAX_COLUMNS, fitting))


class DeviceCard(QToolButton):
    """A checkable card showing a device icon above its name and type.

    Space (built in) and Enter/Return activate it; arrow keys only report
    ``arrow_pressed(key)`` so the grid can move focus (never checking or
    clicking a neighbour). Its serial is the tooltip, the accessible
    description and the ``serial`` property.
    """

    focused = pyqtSignal()
    arrow_pressed = pyqtSignal(int)

    def __init__(self, info: DeviceInfo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._serial = info.serial
        self.setObjectName(CARD_OBJECT_NAME)
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.setIcon(icon_for_type(info.type, CARD_ICON_SIZE))
        self.setIconSize(QSize(CARD_ICON_SIZE, CARD_ICON_SIZE))
        self.setFixedSize(CARD_WIDTH, CARD_HEIGHT)
        name = self.fontMetrics().elidedText(info.name, Qt.TextElideMode.ElideRight,
                                             CARD_TEXT_WIDTH)
        self.setText(f"{name}\n{info.type}")
        self.setToolTip(info.serial)
        self.setAccessibleName(f"{info.name}, {info.type}")
        self.setAccessibleDescription(info.serial)
        self.setProperty(SERIAL_PROPERTY, info.serial)

    @property
    def serial(self) -> str:
        """The serial number of the device this card represents."""
        return self._serial

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 (Qt override)
        """Activate on Enter/Return as well as Space; arrows only request a focus move."""
        if event.key() in ARROW_KEYS:
            event.accept()
            self.arrow_pressed.emit(int(event.key()))
            return
        if event.key() in ACTIVATE_KEYS and not event.isAutoRepeat():
            event.accept()
            self.click()
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event: QFocusEvent) -> None:  # noqa: N802 (Qt override)
        """Report focus so the owning grid can scroll the card into view."""
        super().focusInEvent(event)
        self.focused.emit()


class DeviceGrid(QWidget):
    """Grid of :class:`DeviceCard` objects; at most one card is checked.

    ``device_activated(serial)`` is emitted when a card is clicked or activated
    from the keyboard. The column count follows the available width.
    """

    device_activated = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cards: list[DeviceCard] = []
        self._columns = MIN_COLUMNS
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._container = QWidget()
        self.grid_layout = QGridLayout(self._container)
        self.grid_layout.setSpacing(GRID_SPACING)
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setObjectName(SCROLL_OBJECT_NAME)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.scroll_area.setWidget(self._container)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.scroll_area)
        self.setAccessibleName(GRID_ACCESSIBLE_NAME)

    # -- public API ----------------------------------------------------------

    def set_devices(self, infos: list[DeviceInfo]) -> None:
        """Replace the cards, keeping the checked serial when it is still present."""
        previous = self.selected_serial()
        self._clear()
        for info in infos:
            card = DeviceCard(info, self._container)
            card.clicked.connect(
                lambda _checked=False, serial=info.serial: self.device_activated.emit(serial))
            card.focused.connect(
                lambda card=card: self.scroll_area.ensureWidgetVisible(card))
            card.arrow_pressed.connect(
                lambda key, card=card: self._move_focus(card, key))
            self._group.addButton(card)
            self._cards.append(card)
        self._place_cards()
        if previous is not None:
            self.select_serial(previous)

    def select_serial(self, serial: str | None) -> bool:
        """Check the card for ``serial`` without activating it; False if absent."""
        card = self._card_for(serial)
        if card is None:
            return False
        card.setChecked(True)
        return True

    def selected_serial(self) -> str | None:
        """Serial of the checked card, or None."""
        card = self._group.checkedButton()
        return card.serial if isinstance(card, DeviceCard) else None

    def focus_selected(self) -> None:
        """Give keyboard focus to the checked card (or the first card)."""
        card = self._group.checkedButton() or (self._cards[0] if self._cards else None)
        if card is not None:
            card.setFocus(Qt.FocusReason.OtherFocusReason)

    def count(self) -> int:
        """Number of cards."""
        return len(self._cards)

    def cards(self) -> list[DeviceCard]:
        """The cards in display order."""
        return list(self._cards)

    def columns(self) -> int:
        """Current number of grid columns."""
        return self._columns

    # -- internals -----------------------------------------------------------

    def _card_for(self, serial: str | None) -> DeviceCard | None:
        for card in self._cards:
            if card.serial == serial:
                return card
        return None

    def _move_focus(self, card: DeviceCard, key: int) -> None:
        """Focus the neighbour of ``card`` in the direction of arrow ``key``, if any."""
        steps = {
            Qt.Key.Key_Left: STEP_BACK, Qt.Key.Key_Right: STEP_FORWARD,
            Qt.Key.Key_Up: -self._columns, Qt.Key.Key_Down: self._columns,
        }
        if card not in self._cards:
            return
        target = self._cards.index(card) + steps[Qt.Key(key)]
        if 0 <= target < len(self._cards):
            self._cards[target].setFocus(Qt.FocusReason.TabFocusReason)

    def _clear(self) -> None:
        for card in self._cards:
            self._group.removeButton(card)
            self.grid_layout.removeWidget(card)
            card.hide()
            card.deleteLater()
        self._cards = []

    def _place_cards(self) -> None:
        for card in self._cards:
            self.grid_layout.removeWidget(card)
        for index, card in enumerate(self._cards):
            row, column = divmod(index, self._columns)
            self.grid_layout.addWidget(card, row, column)

    def _available_width(self, width: int) -> int:
        margins = self.grid_layout.contentsMargins()
        scrollbar = self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)
        frame = FRAME_SIDES * self.scroll_area.frameWidth()
        return width - frame - scrollbar - margins.left() - margins.right()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 (Qt override)
        """Re-flow the cards when the number of fitting columns changes."""
        super().resizeEvent(event)
        columns = columns_for_width(self._available_width(event.size().width()))
        if columns != self._columns:
            self._columns = columns
            self._place_cards()
