# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Widget and layout builders for the system monitor page (see :mod:`sysmon_page`).

The ``create_*`` functions put the controls on the page as attributes; the
``*_card`` functions arrange them in section cards. The disk table helpers
fill the table from DiskSpecs and read it back, reporting unparsable rows as
problems instead of raising.
"""

from pathlib import Path
from typing import Any, Iterable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QFormLayout, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QPushButton, QRadioButton, QScrollArea, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from hueberry.sysmon import collector
from hueberry.sysmon.config import (
    ALIGN_CENTER, ALIGN_END, ALIGN_START, EDGE_BOTTOM, EDGE_LEFT, EDGE_RIGHT, EDGE_TOP,
    GPU_CARD_AUTO, GPU_CARD_RE, MARGIN_SIDES, MAX_MARGIN, MAX_SIZE_PX, MIN_MARGIN, MIN_SIZE_PX,
    DiskSpec,
)
from hueberry.ui import layouts, theme

__all__ = ["append_disk_row", "build_body", "create_widgets", "detect_disks",
           "detect_gpu_cards", "read_disk_rows", "set_disk_rows"]

DISPLAY_TITLE = "Display"
DATA_TITLE = "Data"
POSITION_TITLE = "Position"
ORIENTATION_TITLE = "Orientation"
KEY_TITLE = "Toggle key"
SHOW_TEXT = "&Show"
HIDE_TEXT = "&Hide"
# (metric, check box text, accessible name)
METRIC_LABELS = (("cpu", "C&PU", "Show CPU usage"), ("gpu", "&GPU", "Show GPU usage"),
                 ("vram", "&VRAM", "Show VRAM usage"), ("ram", "&RAM", "Show RAM usage"),
                 ("disks", "Dis&ks", "Show disk activity"))
DISK_HEADERS = ("Device", "Label", "Max MB/s")
DISK_COLUMN_COUNT = len(DISK_HEADERS)
COL_DEVICE, COL_LABEL, COL_MAX = range(DISK_COLUMN_COUNT)
DEFAULT_MAX_TEXT = format(collector.DEFAULT_DISK_MAX_MBPS, "g")
DISK_MAX_INVALID_TEXT = "disk row {row}: max MB/s {value!r} is not a number"
GPU_AUTO_TEXT = "Automatic"
EDGE_CHOICES = ((EDGE_TOP, "Top"), (EDGE_BOTTOM, "Bottom"), (EDGE_LEFT, "Left"),
                (EDGE_RIGHT, "Right"))
ALIGN_CHOICES = ((ALIGN_START, "Start"), (ALIGN_CENTER, "Center"), (ALIGN_END, "End"))
AUTO_SIZE_TEXT = "Auto"
PIXEL_SUFFIX = " px"
KEY_HELP_TEXT = (
    "To show or hide the overlay with a device key, bind the key to a macro with the "
    "'App action \u2192 Toggle system monitor' step. From a script or a desktop shortcut, "
    "run `hueberry --toggle-sysmon`."
)


def detect_disks() -> tuple[DiskSpec, ...]:
    """Block devices of this machine (the default disk detector)."""
    return collector.detect_disks(collector.DEFAULT_ROOT)


def detect_gpu_cards(root: Path = collector.DEFAULT_ROOT) -> list[str]:
    """DRM cards (sorted, unique) exposing a GPU busy counter below ``root``."""
    try:
        paths = sorted((root / collector.DRM_CLASS_DIR).glob(collector.GPU_CARD_GLOB))
    except OSError:
        return []
    cards = dict.fromkeys(path.parent.parent.name for path in paths)
    return [card for card in cards if GPU_CARD_RE.fullmatch(card)]


# -- widgets -------------------------------------------------------------------

def create_widgets(page: Any) -> None:
    """Create every section control as an attribute of ``page``."""
    _create_display(page)
    _create_data(page)
    _create_position(page)
    _create_orientation(page)
    _create_key(page)


def _create_display(page: Any) -> None:
    page.toggle_button = QPushButton(SHOW_TEXT, page)
    page.toggle_button.setCheckable(True)
    page.toggle_button.setAccessibleName("Show or hide the system monitor overlay")
    page.state_label = QLabel(page)
    page.state_label.setWordWrap(True)
    page.state_label.setAccessibleName("System monitor state")


def _create_data(page: Any) -> None:
    page.metric_boxes = {}
    for metric, text, name in METRIC_LABELS:
        box = QCheckBox(text, page)
        box.setAccessibleName(name)
        page.metric_boxes[metric] = box
    table = QTableWidget(0, DISK_COLUMN_COUNT, page)
    table.setHorizontalHeaderLabels(list(DISK_HEADERS))
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setTabKeyNavigation(False)  # Tab leaves the table; arrows move inside it
    table.setAccessibleName("Monitored disks")
    page.disk_table = table
    page.add_disk_button = QPushButton("A&dd disk", page)
    page.add_disk_button.setAccessibleName("Add a disk row")
    page.remove_disk_button = QPushButton("Re&move disk", page)
    page.remove_disk_button.setAccessibleName("Remove the selected disk row")
    page.gpu_combo = QComboBox(page)
    page.gpu_combo.setAccessibleName("GPU card")


def _combo(page: Any, choices: Iterable[tuple[str, str]], name: str) -> QComboBox:
    combo = QComboBox(page)
    for value, text in choices:
        combo.addItem(text, value)
    combo.setAccessibleName(name)
    return combo


def _spin(page: Any, low: int, high: int, name: str, auto: bool = False) -> QSpinBox:
    spin = QSpinBox(page)
    spin.setRange(low, high)
    spin.setSuffix(PIXEL_SUFFIX)
    if auto:
        spin.setSpecialValueText(AUTO_SIZE_TEXT)  # shown for the minimum, 0 = automatic
    spin.setAccessibleName(name)
    return spin


def _create_position(page: Any) -> None:
    page.edge_combo = _combo(page, EDGE_CHOICES, "Screen edge")
    page.align_combo = _combo(page, ALIGN_CHOICES, "Alignment along the edge")
    page.margin_spins = {side: _spin(page, MIN_MARGIN, MAX_MARGIN, f"{side.capitalize()} margin")
                         for side in MARGIN_SIDES}
    page.width_spin = _spin(page, MIN_SIZE_PX, MAX_SIZE_PX, "Width (0 = automatic)", auto=True)
    page.height_spin = _spin(page, MIN_SIZE_PX, MAX_SIZE_PX, "Height (0 = automatic)", auto=True)


def _create_orientation(page: Any) -> None:
    page.row_radio = QRadioButton("In a ro&w", page)
    page.row_radio.setAccessibleName("Metrics in a row")
    page.stacked_radio = QRadioButton("S&tacked", page)
    page.stacked_radio.setAccessibleName("Metrics stacked")
    page.orientation_group = QButtonGroup(page)
    for radio in (page.row_radio, page.stacked_radio):
        page.orientation_group.addButton(radio)
    page.row_radio.setChecked(True)


def _create_key(page: Any) -> None:
    page.key_help_label = QLabel(KEY_HELP_TEXT, page)
    page.key_help_label.setTextFormat(Qt.TextFormat.PlainText)
    page.key_help_label.setWordWrap(True)
    theme.set_role(page.key_help_label, "muted")
    page.bind_button = QPushButton("&Bind a device key\u2026", page)
    page.bind_button.setAccessibleName("Bind a device key to toggle the system monitor")


# -- layout --------------------------------------------------------------------

def build_body(page: Any) -> QScrollArea:
    """A scroll area holding every section card of ``page``."""
    content = QWidget(page)
    body = QVBoxLayout(content)
    body.setContentsMargins(0, 0, 0, 0)
    body.setSpacing(theme.SPACING_M)
    for build in (_display_card, _data_card, _position_card, _orientation_card, _key_card):
        body.addWidget(build(page))
    body.addStretch(1)
    scroll = QScrollArea(page)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    scroll.setWidget(content)
    return scroll


def _row(*widgets: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(theme.SPACING_M)
    for widget in widgets:
        row.addWidget(widget)
    row.addStretch(1)
    return row


def _form(layout: QVBoxLayout) -> QFormLayout:
    form = QFormLayout()
    layouts.configure_form(form)
    layout.addLayout(form)
    return form


def _display_card(page: Any) -> QFrame:
    card, layout = layouts.section_card(DISPLAY_TITLE, page)
    row = _row(page.toggle_button)
    row.insertWidget(1, page.state_label, 1)
    layout.addLayout(row)
    return card


def _data_card(page: Any) -> QFrame:
    card, layout = layouts.section_card(DATA_TITLE, page)
    layout.addLayout(_row(*page.metric_boxes.values()))
    layout.addWidget(page.disk_table)
    layout.addLayout(_row(page.add_disk_button, page.remove_disk_button))
    _form(layout).addRow("GPU &card", page.gpu_combo)
    return card


def _position_card(page: Any) -> QFrame:
    card, layout = layouts.section_card(POSITION_TITLE, page)
    form = _form(layout)
    form.addRow("&Edge", page.edge_combo)
    form.addRow("A&lignment", page.align_combo)
    for side, spin in page.margin_spins.items():
        form.addRow(f"{side.capitalize()} margin", spin)
    form.addRow("W&idth", page.width_spin)
    form.addRow("Height", page.height_spin)
    return card


def _orientation_card(page: Any) -> QFrame:
    card, layout = layouts.section_card(ORIENTATION_TITLE, page)
    layout.addLayout(_row(page.row_radio, page.stacked_radio))
    return card


def _key_card(page: Any) -> QFrame:
    card, layout = layouts.section_card(KEY_TITLE, page)
    layout.addWidget(page.key_help_label)
    layout.addLayout(_row(page.bind_button))
    return card


# -- disk table ----------------------------------------------------------------

def append_disk_row(table: QTableWidget, device: str, label: str, max_text: str) -> int:
    """Append an editable row and return its index."""
    row = table.rowCount()
    table.insertRow(row)
    for column, text in ((COL_DEVICE, device), (COL_LABEL, label), (COL_MAX, max_text)):
        table.setItem(row, column, QTableWidgetItem(text))
    return row


def set_disk_rows(table: QTableWidget, disks: Iterable[DiskSpec]) -> None:
    """Replace the table contents with ``disks``."""
    table.setRowCount(0)
    for disk in disks:
        append_disk_row(table, disk.device, disk.label, format(disk.max_mbps, "g"))


def _cell_text(table: QTableWidget, row: int, column: int) -> str:
    item = table.item(row, column)
    return item.text().strip() if item is not None else ""


def read_disk_rows(table: QTableWidget) -> tuple[tuple[DiskSpec, ...], list[str]]:
    """``(disks, problems)`` from the table; blank rows are skipped, bad numbers reported."""
    disks: list[DiskSpec] = []
    problems: list[str] = []
    for row in range(table.rowCount()):
        device, label, max_text = (_cell_text(table, row, column)
                                   for column in range(DISK_COLUMN_COUNT))
        if not (device or label or max_text):
            continue
        try:
            max_mbps = float(max_text)
        except ValueError:
            problems.append(DISK_MAX_INVALID_TEXT.format(row=row + 1, value=max_text))
            continue
        disks.append(DiskSpec(device, label or device, max_mbps))
    return tuple(disks), problems
