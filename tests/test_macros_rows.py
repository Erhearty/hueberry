# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the Macros page list rows: chips, badges, empty states, selection and keyboard."""

import pytest
from PyQt6.QtCore import Qt

from hueberry.macros import store
from hueberry.macros.model import DeviceMacros, KeyStep, Macro, MacroConfig
from hueberry.ui import worker
from hueberry.ui.macros_page import MacrosPage
from macros_page_helpers import KEYBOARD, MOUSE, OLD_PAD, FakeEngine
from macros_page_helpers import add_macro as _add_macro
from macros_page_helpers import device_texts as _device_texts
from macros_page_helpers import make_page as _page
from macros_page_helpers import row_widget as _row
from macros_page_helpers import run_sync as _run_sync
from macros_page_helpers import select as _select


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(worker, "run_async", _run_sync)
    return tmp_path


def test_device_rows_show_state_chips(qtbot):
    store.save(MacroConfig([DeviceMacros(OLD_PAD, "Old Pad", [])]))
    page = _page(qtbot, FakeEngine())
    chips = {page.device_list.item(row).data(Qt.ItemDataRole.UserRole):
             _row(page.device_list, row).state_chip for row in range(page.device_list.count())}
    assert chips[MOUSE].objectName() == "stateChip"
    assert chips[MOUSE].property("state") == "active"
    assert chips[MOUSE].text() == "grabbed"
    assert chips[KEYBOARD].property("state") == "idle"
    assert chips[OLD_PAD].property("state") == "offline"


@pytest.mark.parametrize(("mode", "count", "badge"), [
    ("once", 1, "Once"), ("times", 5, "\u00d75"), ("toggle", 1, "\u221e Toggle")])
def test_macro_row_repeat_badge(qtbot, mode, count, badge):
    macro = Macro("m1", "Loop", True, "BTN_EXTRA", [KeyStep("KEY_B"), KeyStep("KEY_C")],
                  repeat_mode=mode, repeat_count=count)
    store.save(MacroConfig([DeviceMacros(MOUSE, "Test Mouse", [macro])]))
    page = _page(qtbot, FakeEngine())
    _select(page, MOUSE)
    row = _row(page.macro_list)
    assert row.repeat_badge.objectName() == "repeatBadge"
    assert row.repeat_badge.text() == badge
    assert row.trigger_chip.objectName() == "triggerChip"
    assert row.steps_label.text() == "2 steps"
    assert row.steps_label.property("role") == "muted"
    assert page.macro_list.item(0).text() == f"Loop (Button Extra) \u2013 {badge}, 2 steps"
    assert row.enabled_check.accessibleName() == "Enabled: Loop"


LOGI_KEYBOARD = "046d:c33a:Logi Keyboard:usb-4"
RAZER_DOCK = "1532:0f00:Razer Dock:usb-5"
OLD_ENGINE_PAD = "1532:0208:Razer Tartarus:usb-6"
FOREIGN_ROWS = [
    {"identity": LOGI_KEYBOARD, "name": "Logi Keyboard", "has_keys": True, "state": None,
     "vendor": "046d", "kind": "keyboard"},
    {"identity": RAZER_DOCK, "name": "Razer Dock", "has_keys": True, "state": None,
     "vendor": "1532", "kind": "other"}]


def _identities(page):
    return [page.device_list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(page.device_list.count())]


def test_non_razer_and_other_kinds_hidden(qtbot):
    engine = FakeEngine()
    engine.extra_devices = list(FOREIGN_ROWS)
    page = _page(qtbot, engine)
    assert sorted(_identities(page)) == sorted([MOUSE, KEYBOARD])


def test_foreign_device_with_saved_macros_still_listed(qtbot):
    macro = Macro("m1", "Copy", True, "KEY_F1", [KeyStep("KEY_C")])
    store.save(MacroConfig([DeviceMacros(LOGI_KEYBOARD, "Logi Keyboard", [macro])]))
    engine = FakeEngine()
    engine.extra_devices = list(FOREIGN_ROWS)
    page = _page(qtbot, engine)
    assert LOGI_KEYBOARD in _identities(page)
    assert "Logi Keyboard (keyboard) \u2013 idle" in _device_texts(page)
    assert RAZER_DOCK not in _identities(page)


def test_device_rows_use_engine_kind_for_icon(qtbot):
    page = _page(qtbot, FakeEngine())
    kinds = {page.device_list.item(row).data(Qt.ItemDataRole.UserRole):
             _row(page.device_list, row).icon_kind for row in range(page.device_list.count())}
    assert kinds[MOUSE] == "mouse"
    assert kinds[KEYBOARD] == "keyboard"


def test_old_engine_row_without_vendor_or_kind_listed(qtbot):
    engine = FakeEngine()
    engine.extra_devices = [{"identity": OLD_ENGINE_PAD, "name": "Razer Tartarus", "has_keys": True,
                             "state": None}]
    page = _page(qtbot, engine)
    assert OLD_ENGINE_PAD in _identities(page)
    assert "Razer Tartarus \u2013 idle" in _device_texts(page)


def test_empty_state_hints(qtbot):
    page = MacrosPage(None)
    qtbot.addWidget(page)
    assert not page.device_empty_label.isHidden()
    assert page.device_empty_label.property("role") == "muted"
    assert "No Razer keyboard or mouse found" in page.device_empty_label.text()
    assert not page.macro_empty_label.isHidden()
    page = _page(qtbot, FakeEngine())
    _select(page, MOUSE)
    assert page.device_empty_label.isHidden()
    assert "No macros yet" in page.macro_empty_label.text()
    assert not page.macro_empty_label.isHidden()
    _add_macro(page)
    assert page.macro_empty_label.isHidden()


def test_edit_delete_need_selection(qtbot):
    page = _page(qtbot, FakeEngine())
    _select(page, MOUSE)
    _add_macro(page)
    page.macro_list.setCurrentRow(-1)
    assert not page.edit_button.isEnabled()
    assert not page.delete_button.isEnabled()
    page.macro_list.setCurrentRow(0)
    assert page.edit_button.isEnabled() and page.delete_button.isEnabled()


def test_enabled_switch_syncs_with_check_state(qtbot):
    page = _page(qtbot, FakeEngine())
    _select(page, MOUSE)
    _add_macro(page)
    item, row = page.macro_list.item(0), _row(page.macro_list)
    assert row.enabled_check.isChecked()
    item.setCheckState(Qt.CheckState.Unchecked)
    assert not row.enabled_check.isChecked()
    row.enabled_check.setChecked(True)
    assert item.checkState() == Qt.CheckState.Checked
    assert page._device_macros().macros[0].enabled


def test_keyboard_space_toggles_and_enter_edits(qtbot):
    page = _page(qtbot, FakeEngine())
    _select(page, MOUSE)
    _add_macro(page)
    page.macro_list.setCurrentRow(0)
    page.editor = None
    qtbot.keyClick(page.macro_list, Qt.Key.Key_Space)
    assert page.macro_list.item(0).checkState() == Qt.CheckState.Unchecked
    assert not _row(page.macro_list).enabled_check.isChecked()
    assert page.editor is None
    qtbot.keyClick(page.macro_list, Qt.Key.Key_Return)
    assert page.editor is not None
