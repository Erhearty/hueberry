# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the Synapse-style device page hero column and section cards (offscreen)."""

import pytest
from PyQt6.QtWidgets import QFrame, QLabel, QSizePolicy

from hueberry.backend.devices import describe_device
from hueberry.backend.effects import EFFECT_CYCLE, EFFECT_STATIC
from hueberry.ui import theme
from hueberry.ui.device_info_panel import DeviceInfoPanel
from hueberry.ui.device_page import (
    HERO_ICON_SIZE, HERO_WIDTH_PX, PREVIEW_MIN_HEIGHT_PX, PREVIEW_MIN_WIDTH_PX, DevicePage,
)
from hueberry.ui.main_window import DEFAULT_HEIGHT
from hueberry.ui.mouse_panel import MousePanel

MOUSE_CAPS = ("dpi", "poll_rate")
# Like MATRIX_CAPS in test_lighting_presets.py, plus spectrum to switch effects.
LIGHTING_CAPS = ("lighting", "lighting_static", "lighting_breath_dual", "lighting_led_matrix",
                 "lighting_spectrum")
KEYBOARD_SERIAL = "KBD1"
# Room left in the main window for the app header bar and the daemon status bar.
WINDOW_CHROME_ALLOWANCE_PX = 80
# Qt's QWIDGETSIZE_MAX: the default maximum width/height of an unconstrained widget.
QWIDGETSIZE_MAX = 16777215
# Page sizes (width, height) for the resize tests; SMALL is above the page's minimum.
SMALL_PAGE = (900, 600)
LARGE_PAGE = (1400, 1000)
# Slack for the tab widget not filling the body exactly (rounding, frame).
BODY_FILL_TOLERANCE_PX = 8


def _cards(widget):
    """Section cards under ``widget``, in creation order."""
    return [frame for frame in widget.findChildren(QFrame)
            if frame.objectName() == theme.SECTION_OBJECT_NAME]


def _header_text(card):
    header = card.layout().itemAt(0).widget()
    assert isinstance(header, QLabel)
    return header.text()


def _hero_widgets(page):
    """Widgets of the hero column, top to bottom (the stretch is skipped)."""
    column = page.layout().itemAt(1).layout().itemAt(0).widget().layout()
    items = (column.itemAt(i) for i in range(column.count()))
    return [item.widget() for item in items if item.widget() is not None]


def _lit_device(page, make_device):
    dev = make_device(device_type="keyboard", serial=KEYBOARD_SERIAL,
                      capabilities=LIGHTING_CAPS)
    page.set_device(dev, describe_device(dev))
    return dev


@pytest.fixture
def page(qtbot):
    widget = DevicePage()
    qtbot.addWidget(widget)
    return widget


def test_hero_pixmap_and_type_after_set_device(page, make_device):
    dev = make_device(device_type="mouse", capabilities=MOUSE_CAPS)
    info = describe_device(dev)
    page.set_device(dev, info)
    pixmap = page.icon_label.pixmap()
    assert (pixmap.width(), pixmap.height()) == (HERO_ICON_SIZE, HERO_ICON_SIZE)
    assert page.type_label.text() == info.type
    assert page.type_label.property("role") == "muted"


def test_hero_cleared_without_device(page, make_device):
    dev = make_device(device_type="mouse", capabilities=MOUSE_CAPS)
    page.set_device(dev, describe_device(dev))
    page.set_device(None, None)
    assert page.type_label.text() == ""
    assert page.icon_label.pixmap().isNull()


def test_hero_column_width_and_body_order(page):
    body = page.layout().itemAt(1).layout()
    hero = body.itemAt(0).widget()
    assert hero.width() == HERO_WIDTH_PX or hero.maximumWidth() == HERO_WIDTH_PX
    assert hero.isAncestorOf(page.icon_label)
    assert hero.isAncestorOf(page.type_label)
    assert body.itemAt(1).widget() is page.tabs
    assert body.stretch(1) == 1


def test_hero_order_without_preview(page):
    assert _hero_widgets(page) == [page.icon_label, page.type_label]
    hero = page.layout().itemAt(1).layout().itemAt(0).widget()
    column = hero.layout()
    assert column.itemAt(column.count() - 1).spacerItem() is not None
    assert not hero.isAncestorOf(page.lighting_preview)
    assert page.lighting_preview.isHidden()


def _resize_and_layout(page, size):
    page.resize(*size)
    page.layout().activate()


def test_preview_fills_bottom(page):
    outer = page.layout()
    assert outer.count() == 3
    assert outer.itemAt(2).widget() is page.lighting_preview
    assert (outer.stretch(1), outer.stretch(2)) == (0, 1)
    preview = page.lighting_preview
    assert preview.minimumWidth() == PREVIEW_MIN_WIDTH_PX
    assert preview.minimumHeight() == PREVIEW_MIN_HEIGHT_PX
    assert preview.maximumWidth() == QWIDGETSIZE_MAX
    assert preview.maximumHeight() == QWIDGETSIZE_MAX
    policy = preview.sizePolicy()
    assert policy.horizontalPolicy() == QSizePolicy.Policy.Expanding
    assert policy.verticalPolicy() == QSizePolicy.Policy.Expanding


def test_preview_grows_with_window(page, make_device):
    _lit_device(page, make_device)
    page.show()
    minimum = page.minimumSizeHint()
    assert SMALL_PAGE[0] >= minimum.width() and SMALL_PAGE[1] >= minimum.height()
    preview = page.lighting_preview
    _resize_and_layout(page, SMALL_PAGE)
    small = preview.size()
    _resize_and_layout(page, LARGE_PAGE)
    assert preview.width() > small.width()
    assert preview.height() > small.height()
    margins = page.layout().contentsMargins()
    assert preview.width() == page.width() - margins.left() - margins.right()
    _resize_and_layout(page, SMALL_PAGE)
    assert preview.size() == small


def test_hidden_preview_gives_body_the_space(page):
    page.show()
    _resize_and_layout(page, LARGE_PAGE)
    assert page.lighting_preview.isHidden()
    outer = page.layout()
    margins = outer.contentsMargins()
    header_height = outer.itemAt(0).geometry().height()
    available = (page.height() - header_height - margins.top() - margins.bottom()
                 - outer.spacing())
    assert page.tabs.height() >= available - BODY_FILL_TOLERANCE_PX


def test_page_with_preview_fits_default_window(page):
    """The shown preview must not force the window taller than its default height."""
    page.lighting_preview.setVisible(True)
    page.layout().activate()
    needed = page.minimumSizeHint().height() + WINDOW_CHROME_ALLOWANCE_PX
    assert needed <= DEFAULT_HEIGHT


def test_preview_shows_lighting_device(page, make_device):
    _lit_device(page, make_device)
    preview = page.lighting_preview
    assert not preview.isHidden()
    assert [d.serial for d in preview.devices()] == [KEYBOARD_SERIAL]
    assert preview.preset() is not None


def test_preview_follows_effect(page, make_device):
    _lit_device(page, make_device)
    combo = page.lighting_panel.effect_combo
    combo.setCurrentIndex(combo.findData("static"))
    assert page.lighting_preview.preset().effect == EFFECT_STATIC
    combo.setCurrentIndex(combo.findData("spectrum"))
    assert page.lighting_preview.preset().effect == EFFECT_CYCLE


def test_preview_hidden_when_cleared(page, make_device):
    _lit_device(page, make_device)
    page.set_device(None, None)
    assert page.lighting_preview.isHidden()
    assert page.lighting_preview.devices() == ()


def test_preview_hidden_without_lighting(page, make_device):
    dev = make_device(device_type="mouse", capabilities=MOUSE_CAPS)
    page.set_device(dev, describe_device(dev))
    assert page.lighting_preview.isHidden()
    assert page.lighting_preview.devices() == ()


def test_mouse_panel_has_two_cards(qtbot):
    panel = MousePanel()
    qtbot.addWidget(panel)
    cards = _cards(panel)
    assert [_header_text(card) for card in cards] == ["Sensitivity", "Polling rate"]
    assert cards[0].isAncestorOf(panel.dpi_x_spin)
    assert cards[0].isAncestorOf(panel.dpi_y_spin)
    assert cards[1].isAncestorOf(panel.poll_combo)
    assert not any(card.isAncestorOf(panel.apply_button) for card in cards)


def test_device_info_panel_has_one_card(qtbot):
    panel = DeviceInfoPanel()
    qtbot.addWidget(panel)
    cards = _cards(panel)
    assert [_header_text(card) for card in cards] == ["Device"]
    assert all(cards[0].isAncestorOf(label) for label in panel.values.values())
