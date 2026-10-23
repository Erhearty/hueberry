# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""The Macros page passes the other present keyboards and mice to the editor as ``also_identities``."""

import pytest

from hueberry.macros.model import KeyStep, Macro
from hueberry.ui import macros_page, worker
from macros_page_helpers import MOUSE, KEYBOARD, FakeEngine, make_page, run_sync, select

EXTRA_KEYBOARD = "1532:0300:Extra Keyboard:usb-4"
KINDLESS = "1532:0400:Kindless:usb-5"  # an older engine's row without a kind: never offered
GONE = "1532:0500:Gone Keyboard:usb-6"  # configured or known, but not present


class _Signal:
    def connect(self, slot):
        self.slot = slot


class _EditorStub:
    """Records the arguments the page builds the editor with; never shows a dialog."""

    def __init__(self, macro, **kwargs):
        self.kwargs = kwargs
        self.accepted = _Signal()

    def open(self):
        pass


class _Engine(FakeEngine):
    def __init__(self):
        super().__init__()
        self.extra_devices = [
            {"identity": EXTRA_KEYBOARD, "name": "Extra Keyboard", "has_keys": True, "state": None,
             "vendor": "1532", "kind": "keyboard"},
            {"identity": KINDLESS, "name": "Kindless", "has_keys": True, "state": None, "vendor": "1532"},
        ]

    def status(self):
        status = super().status()
        status["devices"].append({"identity": GONE, "name": "Gone Keyboard", "state": None, "error": None})
        return status


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(worker, "run_async", run_sync)
    monkeypatch.setattr(macros_page, "MacroEditorDialog", _EditorStub)


def test_also_identities_are_present_keyboards_and_mice_except_the_edited_one(qtbot):
    page = make_page(qtbot, _Engine())
    select(page, MOUSE)
    page._open_editor(Macro("m1", "Copy", True, "BTN_SIDE", [KeyStep("KEY_A")]), None)
    assert sorted(page.editor.kwargs["also_identities"]) == sorted([KEYBOARD, EXTRA_KEYBOARD])
