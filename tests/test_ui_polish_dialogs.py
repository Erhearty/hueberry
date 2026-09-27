# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Visual-polish roles on the macro dialogs and the device grid spacing token."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialogButtonBox, QFormLayout

from hueberry.macros.model import KeyStep, Macro
from hueberry.ui import device_cards, theme
from hueberry.ui.macro_editor import MacroEditorDialog, StepDialog
from hueberry.ui.macro_recorder import RecorderDialog

IDENTITY = "1532:0084:Test Mouse:usb-1"
LABEL_ALIGNMENT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


def _macro(steps):
    """A macro with the given ``steps``."""
    return Macro(id="m1", name="Test", enabled=True, trigger="BTN_SIDE", steps=steps)


def _ok(dialog):
    """Return the dialog's OK button."""
    return dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)


def test_validation_role_toggles(qtbot):
    dialog = MacroEditorDialog(_macro([]))
    qtbot.addWidget(dialog)
    assert dialog.validation_label.property("role") == "error"
    assert dialog.validation_label.styleSheet() == ""
    dialog._steps = [KeyStep("KEY_A", "tap")]
    dialog._validate()
    assert dialog.validation_label.property("role") == "muted"


def test_ok_buttons_are_primary(qtbot):
    editor = MacroEditorDialog(_macro([]))
    step = StepDialog()
    for dialog in (editor, step):
        qtbot.addWidget(dialog)
        assert _ok(dialog).property("role") == "primary"
        for form in dialog.findChildren(QFormLayout):
            assert form.labelAlignment() == LABEL_ALIGNMENT


def test_recorder_start_is_primary(qtbot):
    dialog = RecorderDialog(object(), IDENTITY)
    qtbot.addWidget(dialog)
    assert dialog.start_button.property("role") == "primary"


def test_grid_spacing_uses_token():
    assert device_cards.GRID_SPACING == theme.SPACING_M
