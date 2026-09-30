# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the system monitor settings page (with a fake controller)."""

import dataclasses

import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QPushButton, QRadioButton, QSpinBox, QTableWidget,
)

from hueberry.sysmon.config import (
    ALIGN_BOTTOM, ALIGN_CENTER, ALIGN_LEFT, ALIGN_RIGHT, ALIGN_TOP, ORIENTATION_STACKED, DiskSpec,
    SysmonConfig,
)
from hueberry.ui import sysmon_sections
from hueberry.ui.sysmon_page import APPLIED_TEXT, SysmonPage

DETECTED_DISK = DiskSpec("nvme0n1", "NVMe", 500.0)
DETECTED_CARDS = ["card0", "card1"]
START_ERROR = "waybar not found"
MARGIN_TOP = 12
MARGIN_LEFT = 7
HEIGHT = 30
SDA_MAX = 250.0
COL_DEVICE, COL_LABEL, COL_MAX = (sysmon_sections.COL_DEVICE, sysmon_sections.COL_LABEL,
                                  sysmon_sections.COL_MAX)
CONTROL_TYPES = (QPushButton, QCheckBox, QComboBox, QSpinBox, QRadioButton, QTableWidget)


class FakeController(QObject):
    """Records apply calls; start/stop flip ``running`` and emit ``state_changed``."""

    state_changed = pyqtSignal(bool)

    def __init__(self, config: SysmonConfig | None = None) -> None:
        super().__init__()
        self.config = config or SysmonConfig()
        self.applied: list[SysmonConfig] = []
        self.running = False
        self.start_ok = True
        self.last_error: str | None = None

    def is_running(self) -> bool:
        return self.running

    def start(self) -> bool:
        if not self.start_ok:
            self.last_error = START_ERROR
            return False
        self.running = True
        self.state_changed.emit(True)
        return True

    def stop(self) -> None:
        self.running = False
        self.state_changed.emit(False)

    def apply(self, cfg: SysmonConfig) -> list[str]:
        self.applied.append(cfg)
        found = cfg.problems()
        if not found:
            self.config = cfg
        return found


@pytest.fixture
def controller():
    return FakeController()


@pytest.fixture
def page(qtbot, controller):
    widget = SysmonPage(controller, disk_detector=lambda: (DETECTED_DISK,),
                        gpu_detector=lambda: list(DETECTED_CARDS))
    qtbot.addWidget(widget)
    return widget


@pytest.fixture
def messages(page):
    received: list[str] = []
    page.status.connect(received.append)
    return received


def _cell(page, row, column):
    return page.disk_table.item(row, column).text()


def _set_cell(page, row, column, text):
    page.disk_table.item(row, column).setText(text)


def _select(combo, value):
    combo.setCurrentIndex(combo.findData(value))


def test_prefills_detected_disks_and_cards(page):
    assert page.disk_table.rowCount() == 1
    assert [_cell(page, 0, col) for col in (COL_DEVICE, COL_LABEL, COL_MAX)] == [
        "nvme0n1", "NVMe", "500"]
    cards = [page.gpu_combo.itemData(i) for i in range(page.gpu_combo.count())]
    assert cards == ["auto"] + DETECTED_CARDS
    assert page.gpu_combo.currentData() == "auto"


def test_configured_disks_win_over_detected(qtbot):
    ctrl = FakeController(SysmonConfig(disks=(DiskSpec("sdb", "Data", 100.0),)))
    widget = SysmonPage(ctrl, disk_detector=lambda: (DETECTED_DISK,), gpu_detector=list)
    qtbot.addWidget(widget)
    assert widget.disk_table.rowCount() == 1
    assert _cell(widget, 0, COL_DEVICE) == "sdb"


def test_edit_and_apply_passes_expected_config(page, controller, messages):
    page.metric_boxes["gpu"].setChecked(False)
    _set_cell(page, 0, COL_LABEL, "Fast")
    page.add_disk_button.click()
    for column, text in ((COL_DEVICE, "sda"), (COL_LABEL, "Slow"), (COL_MAX, "250")):
        _set_cell(page, 1, column, text)
    _select(page.gpu_combo, "card1")
    _select(page.align_x_combo, ALIGN_LEFT)
    _select(page.align_y_combo, ALIGN_CENTER)
    page.margin_spins["top"].setValue(MARGIN_TOP)
    page.margin_spins["left"].setValue(MARGIN_LEFT)
    page.width_spin.setValue(0)
    page.height_spin.setValue(HEIGHT)
    page.stacked_radio.setChecked(True)
    page.apply_button.click()
    expected = dataclasses.replace(
        SysmonConfig(), show_gpu=False, gpu_card="card1",
        align_x=ALIGN_LEFT, align_y=ALIGN_CENTER, orientation=ORIENTATION_STACKED, margin_top=MARGIN_TOP,
        margin_left=MARGIN_LEFT, width=0, height=HEIGHT,
        disks=(DiskSpec("nvme0n1", "Fast", 500.0), DiskSpec("sda", "Slow", SDA_MAX)))
    assert controller.applied == [expected]
    assert messages == [APPLIED_TEXT]
    assert page.problems_label.isHidden()


def test_align_choices_are_three_each(page):
    xs = [page.align_x_combo.itemData(i) for i in range(page.align_x_combo.count())]
    ys = [page.align_y_combo.itemData(i) for i in range(page.align_y_combo.count())]
    assert xs == ["left", "center", "right"]
    assert ys == ["top", "center", "bottom"]


def test_right_top_applies_and_both_combos_enabled(page, controller):
    _select(page.align_x_combo, ALIGN_RIGHT)
    _select(page.align_y_combo, ALIGN_TOP)
    page.apply_button.click()
    assert controller.applied[-1].align_x == "right"
    assert controller.applied[-1].align_y == "top"
    assert page.align_x_combo.isEnabled() and page.align_y_combo.isEnabled()


def test_blank_disk_rows_are_ignored(page, controller):
    page.add_disk_button.click()
    _set_cell(page, 1, COL_MAX, "")
    page.apply_button.click()
    assert controller.applied[-1].disks == (DETECTED_DISK,)


def test_unparsable_disk_max_is_a_problem(page, controller, messages):
    _set_cell(page, 0, COL_MAX, "fast")
    page.apply_button.click()
    assert controller.applied == []
    assert not page.problems_label.isHidden()
    assert "'fast' is not a number" in page.problems_label.text()
    assert len(messages) == 1 and "'fast'" in messages[0]


def test_controller_problems_are_shown(page, controller, messages):
    _set_cell(page, 0, COL_DEVICE, "/dev/sda")
    page.apply_button.click()
    assert len(controller.applied) == 1
    assert "device name like 'sda'" in page.problems_label.text()
    assert not page.problems_label.isHidden()
    assert messages[0].startswith("Cannot apply:")


def test_remove_disk_row(page):
    page.disk_table.setCurrentCell(0, COL_DEVICE)
    page.remove_disk_button.click()
    assert page.disk_table.rowCount() == 0


def test_toggle_button_follows_state_signal(page, controller):
    assert not page.toggle_button.isChecked()
    assert page.toggle_button.text() == sysmon_sections.SHOW_TEXT
    controller.state_changed.emit(True)
    assert page.toggle_button.isChecked()
    assert page.toggle_button.text() == sysmon_sections.HIDE_TEXT
    controller.state_changed.emit(False)
    assert not page.toggle_button.isChecked()


def test_toggle_button_starts_and_stops(page, controller):
    page.toggle_button.click()
    assert controller.running and page.toggle_button.isChecked()
    page.toggle_button.click()
    assert not controller.running and not page.toggle_button.isChecked()


def test_failed_start_shows_last_error(page, controller, messages):
    controller.start_ok = False
    page.toggle_button.click()
    assert not page.toggle_button.isChecked()
    assert START_ERROR in page.state_label.text()
    assert messages and START_ERROR in messages[0]


def test_bind_key_and_back_signals(page, qtbot):
    with qtbot.waitSignal(page.bind_key_requested, timeout=0):
        page.bind_button.click()
    with qtbot.waitSignal(page.back_requested, timeout=0):
        page.back_button.click()


def test_refresh_reloads_from_config(page, controller):
    page.metric_boxes["cpu"].setChecked(False)
    controller.config = SysmonConfig(show_cpu=True, show_ram=False, align_x=ALIGN_LEFT,
                                     align_y=ALIGN_BOTTOM,
                                     gpu_card="card5", orientation=ORIENTATION_STACKED,
                                     margin_top=MARGIN_TOP, height=HEIGHT,
                                     disks=(DiskSpec("sdc", "Backup", SDA_MAX),))
    page.refresh()
    assert page.metric_boxes["cpu"].isChecked()
    assert not page.metric_boxes["ram"].isChecked()
    assert page.align_x_combo.currentData() == ALIGN_LEFT
    assert page.align_y_combo.currentData() == ALIGN_BOTTOM
    assert page.gpu_combo.currentData() == "card5"
    assert page.stacked_radio.isChecked()
    assert page.margin_spins["top"].value() == MARGIN_TOP
    assert page.height_spin.value() == HEIGHT
    assert _cell(page, 0, COL_DEVICE) == "sdc"


def test_size_spins_show_auto_for_zero(page):
    page.height_spin.setValue(0)
    assert page.height_spin.text() == sysmon_sections.AUTO_SIZE_TEXT


def test_every_control_has_an_accessible_name(page):
    unnamed = [type(widget).__name__ for kind in CONTROL_TYPES
               for widget in page.findChildren(kind) if not widget.accessibleName()]
    assert unnamed == []


def test_tab_order_follows_focus_order(page):
    expected = [w for w in page.focus_order() if w.focusProxy() is None]
    seen = []
    widget = page.back_button.nextInFocusChain()
    while widget is not page.back_button:
        if widget in expected and widget not in seen:
            seen.append(widget)
        widget = widget.nextInFocusChain()
    assert seen == expected[1:]
