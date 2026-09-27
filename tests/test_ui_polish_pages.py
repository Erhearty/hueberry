# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Visual-polish roles and layouts on the device, macros, presets and empty pages."""

import pytest

from hueberry.ui import theme
from hueberry.ui.device_page import DevicePage
from hueberry.ui.empty_state import EmptyStatePanel
from hueberry.ui.macros_page import MacrosPage
from hueberry.ui.presets_page import PresetsPage


@pytest.fixture
def pages(qtbot):
    """One of each page, owned by qtbot."""
    built = {"device": DevicePage(), "macros": MacrosPage(None),
             "presets": PresetsPage(), "empty": EmptyStatePanel()}
    for widget in built.values():
        qtbot.addWidget(widget)
    return built


def test_title_roles(pages):
    assert pages["device"].name_label.property("role") == "title"
    for name in ("macros", "presets", "empty"):
        label = pages[name].title_label
        assert label.property("role") == "title"
        assert "<b>" not in label.text()


def test_error_roles_without_inline_stylesheet(pages):
    for label in (pages["macros"].banner_label, pages["presets"].error_label):
        assert label.property("role") == "error"
        assert label.styleSheet() == ""


def test_primary_roles(pages):
    for button in (pages["presets"].apply_button, pages["macros"].save_button,
                   pages["empty"].start_button):
        assert button.property("role") == "primary"


def test_page_margins_use_tokens(pages):
    for name in ("device", "macros", "presets"):
        layout = pages[name].layout()
        assert layout.contentsMargins().left() == theme.PAGE_MARGIN_PX
        assert layout.spacing() == theme.SPACING_M


def test_device_header_is_back_then_name(pages):
    page = pages["device"]
    header = page.layout().itemAt(0).layout()
    widgets = [header.itemAt(i).widget() for i in range(2)]
    assert widgets == [page.back_button, page.name_label]


def test_mouse_wrapper_has_zero_margins(pages):
    margins = pages["device"].mouse_page.layout().contentsMargins()
    assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (0, 0, 0, 0)
