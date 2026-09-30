# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Visual-polish form alignment and primary roles on the device/daemon panels."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFormLayout

from hueberry.backend.daemon import DaemonService
from hueberry.ui import theme
from hueberry.ui.daemon_panel import DaemonPanel
from hueberry.ui.device_info_panel import DeviceInfoPanel
from hueberry.ui.lighting_panel import LightingPanel
from hueberry.ui.mouse_panel import MousePanel

LABEL_ALIGNMENT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


def _forms(widget):
    """Every QFormLayout inside ``widget``."""
    return widget.findChildren(QFormLayout)


def _assert_configured(widget):
    """Assert every QFormLayout under ``widget`` went through configure_form."""
    forms = _forms(widget)
    assert forms
    for form in forms:
        assert form.labelAlignment() == LABEL_ALIGNMENT
        assert form.fieldGrowthPolicy() == QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        assert form.horizontalSpacing() == theme.SPACING_M
        assert form.verticalSpacing() == theme.SPACING_S


def test_panel_forms_are_configured(qtbot):
    for widget in (LightingPanel(), MousePanel(), DeviceInfoPanel()):
        qtbot.addWidget(widget)
        _assert_configured(widget)


def test_daemon_panel_form_is_configured(qtbot, tmp_path):
    panel = DaemonPanel(DaemonService(pid_path=tmp_path / "missing.pid"))
    qtbot.addWidget(panel)
    _assert_configured(panel)


def test_apply_buttons_are_primary(qtbot):
    lighting, mouse = LightingPanel(), MousePanel()
    for widget in (lighting, mouse):
        qtbot.addWidget(widget)
    assert lighting.apply_button.property("role") == "primary"
    assert mouse.apply_button.property("role") == "primary"
