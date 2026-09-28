# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""System monitor page: show/hide the Waybar overlay and edit its settings.

The page reads and writes through a ``SysmonController`` (anything with its
``config``, ``is_running``, ``start``, ``stop``, ``apply``, ``last_error`` and
``state_changed``). *Apply* builds a SysmonConfig from the widgets on top of
the controller's current one and hands it to ``controller.apply``; problems
are shown inline and emitted via ``status``. Disk and GPU detection is
injectable so tests never read the real /sys.
"""

import dataclasses
import logging
from typing import Any, Callable, Iterable

from PyQt6.QtCore import QSignalBlocker, pyqtSignal
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QWidget

from hueberry.sysmon.config import (
    GPU_CARD_AUTO, MARGIN_FIELD_PREFIX, METRIC_FIELD_PREFIX, ORIENTATION_ROW,
    ORIENTATION_STACKED, DiskSpec, SysmonConfig,
)
from hueberry.ui import layouts, sysmon_sections, theme

__all__ = ["SysmonPage"]

logger = logging.getLogger(__name__)

TITLE_TEXT = "System monitor"
BACK_TEXT = "\u2190 Back"
APPLY_TEXT = "&Apply"
SHOWN_TEXT = "The overlay is shown"
HIDDEN_TEXT = "The overlay is hidden"
START_FAILED_TEXT = "Could not show the overlay: {error}"
UNKNOWN_ERROR_TEXT = "unknown error"
APPLIED_TEXT = "System monitor settings applied"
PROBLEMS_TEXT = "Cannot apply: {problems}"
PROBLEM_SEPARATOR = "; "
PROBLEM_LINE_SEPARATOR = "\n"

DiskDetector = Callable[[], Iterable[DiskSpec]]
GpuDetector = Callable[[], Iterable[str]]


class SysmonPage(QWidget):
    """Overlay Show/Hide plus the Data, Position, Orientation and Toggle key sections."""

    back_requested = pyqtSignal()
    status = pyqtSignal(str)
    bind_key_requested = pyqtSignal()

    def __init__(self, controller: Any, parent: QWidget | None = None, *,
                 disk_detector: DiskDetector = sysmon_sections.detect_disks,
                 gpu_detector: GpuDetector = sysmon_sections.detect_gpu_cards) -> None:
        super().__init__(parent)
        self._controller = controller
        self._detected_disks = tuple(disk_detector())
        self._detected_cards = list(gpu_detector())
        self._build_widgets()
        self._build_layout()
        self._connect_signals()
        self._set_tab_order()
        self.refresh()
        self._sync_running(controller.is_running())

    # -- construction --------------------------------------------------------

    def _build_widgets(self) -> None:
        self.back_button = QPushButton(BACK_TEXT, self)
        self.back_button.setAccessibleName("Back")
        self.title_label = QLabel(TITLE_TEXT, self)
        self.problems_label = QLabel(self)
        self.problems_label.setWordWrap(True)
        self.problems_label.setAccessibleName("Problems")
        theme.set_role(self.problems_label, "error")
        self.problems_label.hide()
        sysmon_sections.create_widgets(self)
        self.apply_button = QPushButton(APPLY_TEXT, self)
        self.apply_button.setAccessibleName("Apply system monitor settings")
        theme.set_role(self.apply_button, "primary")

    def _build_layout(self) -> None:
        outer = layouts.page_layout(self)
        outer.addLayout(layouts.page_header(self.back_button, self.title_label))
        outer.addWidget(self.problems_label)
        outer.addWidget(sysmon_sections.build_body(self), 1)
        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(self.apply_button)
        outer.addLayout(footer)

    def _connect_signals(self) -> None:
        self.back_button.clicked.connect(self.back_requested)
        self.toggle_button.clicked.connect(self._toggle_clicked)
        self._controller.state_changed.connect(self._sync_running)
        self.add_disk_button.clicked.connect(self._add_disk)
        self.remove_disk_button.clicked.connect(self._remove_disk)
        self.bind_button.clicked.connect(self.bind_key_requested)
        self.apply_button.clicked.connect(self._apply_clicked)

    def focus_order(self) -> list[QWidget]:
        """The page's controls in tab order."""
        return [self.back_button, self.toggle_button, *self.metric_boxes.values(),
                self.disk_table, self.add_disk_button, self.remove_disk_button,
                self.gpu_combo, self.edge_combo, self.align_combo,
                *self.margin_spins.values(), self.width_spin, self.height_spin,
                self.row_radio, self.stacked_radio, self.bind_button, self.apply_button]

    def _set_tab_order(self) -> None:
        chain = self.focus_order()
        for first, second in zip(chain, chain[1:]):
            QWidget.setTabOrder(first, second)

    # -- public API ----------------------------------------------------------

    def refresh(self) -> None:
        """Reload every widget from ``controller.config`` and clear shown problems."""
        cfg = self._controller.config
        for metric, box in self.metric_boxes.items():
            box.setChecked(getattr(cfg, METRIC_FIELD_PREFIX + metric))
        sysmon_sections.set_disk_rows(self.disk_table, cfg.disks or self._detected_disks)
        self._fill_gpu_combo(cfg.gpu_card)
        _select_data(self.edge_combo, cfg.edge)
        _select_data(self.align_combo, cfg.alignment)
        for side, spin in self.margin_spins.items():
            spin.setValue(getattr(cfg, MARGIN_FIELD_PREFIX + side))
        self.width_spin.setValue(cfg.width)
        self.height_spin.setValue(cfg.height)
        self.stacked_radio.setChecked(cfg.orientation == ORIENTATION_STACKED)
        self.row_radio.setChecked(cfg.orientation != ORIENTATION_STACKED)
        self._show_problems([])

    # -- display -------------------------------------------------------------

    def _sync_running(self, running: bool) -> None:
        """Mirror the overlay state on the toggle button and the state label."""
        with QSignalBlocker(self.toggle_button):
            self.toggle_button.setChecked(running)
        self.toggle_button.setText(sysmon_sections.HIDE_TEXT if running
                                   else sysmon_sections.SHOW_TEXT)
        self.state_label.setText(SHOWN_TEXT if running else HIDDEN_TEXT)
        theme.set_role(self.state_label, "muted")

    def _toggle_clicked(self) -> None:
        if self._controller.is_running():
            self._controller.stop()
        elif not self._controller.start():
            self._sync_running(False)
            self._show_start_error()
            return
        self._sync_running(self._controller.is_running())

    def _show_start_error(self) -> None:
        error = self._controller.last_error or UNKNOWN_ERROR_TEXT
        message = START_FAILED_TEXT.format(error=error)
        logger.warning("Sysmon page: %s", message)
        self.state_label.setText(message)
        theme.set_role(self.state_label, "error")
        self.status.emit(message)

    # -- data ----------------------------------------------------------------

    def _fill_gpu_combo(self, current: str) -> None:
        cards = list(self._detected_cards)
        if current != GPU_CARD_AUTO and current not in cards:
            cards.append(current)  # a configured card that is not detected right now
        self.gpu_combo.clear()
        self.gpu_combo.addItem(sysmon_sections.GPU_AUTO_TEXT, GPU_CARD_AUTO)
        for card in cards:
            self.gpu_combo.addItem(card, card)
        _select_data(self.gpu_combo, current)

    def _add_disk(self) -> None:
        row = sysmon_sections.append_disk_row(self.disk_table, "", "",
                                              sysmon_sections.DEFAULT_MAX_TEXT)
        self.disk_table.setCurrentCell(row, sysmon_sections.COL_DEVICE)
        self.disk_table.setFocus()

    def _remove_disk(self) -> None:
        row = self.disk_table.currentRow()
        if row >= 0:
            self.disk_table.removeRow(row)

    # -- apply ---------------------------------------------------------------

    def _collect(self) -> tuple[SysmonConfig, list[str]]:
        """The config the widgets describe, plus problems from unparsable disk rows."""
        disks, problems = sysmon_sections.read_disk_rows(self.disk_table)
        values: dict[str, Any] = {METRIC_FIELD_PREFIX + metric: box.isChecked()
                                  for metric, box in self.metric_boxes.items()}
        values.update({MARGIN_FIELD_PREFIX + side: spin.value()
                       for side, spin in self.margin_spins.items()})
        stacked = self.stacked_radio.isChecked()
        cfg = dataclasses.replace(
            self._controller.config, disks=disks, gpu_card=self.gpu_combo.currentData(),
            edge=self.edge_combo.currentData(), alignment=self.align_combo.currentData(),
            orientation=ORIENTATION_STACKED if stacked else ORIENTATION_ROW,
            width=self.width_spin.value(), height=self.height_spin.value(), **values)
        return cfg, problems

    def _apply_clicked(self) -> None:
        cfg, problems = self._collect()
        if problems:
            problems += cfg.problems()
        else:
            problems = list(self._controller.apply(cfg))
        self._show_problems(problems)
        if problems:
            message = PROBLEMS_TEXT.format(problems=PROBLEM_SEPARATOR.join(problems))
            logger.warning("Sysmon page: %s", message)
            self.status.emit(message)
        else:
            self.status.emit(APPLIED_TEXT)

    def _show_problems(self, problems: list[str]) -> None:
        self.problems_label.setText(PROBLEM_LINE_SEPARATOR.join(problems))
        self.problems_label.setVisible(bool(problems))


def _select_data(combo: QComboBox, value: Any) -> None:
    """Select the item of ``combo`` holding ``value`` (the first item when absent)."""
    index = combo.findData(value)
    combo.setCurrentIndex(index if index >= 0 else 0)
