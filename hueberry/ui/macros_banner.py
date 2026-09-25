# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Texts of the Macros page: the engine banner and device state labels.

Kept apart from :mod:`hueberry.ui.macros_page` so the page stays small; the
page re-exports :func:`banner_text` and :func:`state_label`.
"""

from typing import Any

from hueberry.backend import macro_engine as engine_states

STATE_LABELS = {
    "active": "grabbed", "busy": "busy \u2013 used by another program",
    "permission_denied": "no permission", "error": "error", "inactive": "not grabbed",
    "disconnected": "disconnected", "stopped": "stopped",
    "waiting": "waiting for held keys to be released", None: "idle",
}
BANNER_NO_ENGINE = "Macros cannot run in this session; they can still be edited."
BANNER_EVDEV = ("python-evdev is not installed, so macros cannot run. Install python3-evdev "
                "(or the 'macros' extra) and restart Hueberry; macros can still be edited.")
BANNER_STARTING = "Starting the macro engine\u2026"
BANNER_DOWN = "The macro engine is not running{reason}. Macros can be edited and run once it starts."
BANNER_PERMISSIONS = ("No access to {what}. Install the udev rule, join the 'input' group and "
                      "log in again (see the README).")
BANNER_CONFIG = "macros.json: {error}"


def _permission_problem(permissions: dict) -> str | None:
    missing = []
    if permissions and not permissions.get("uinput_ok", True):
        missing.append("/dev/uinput")
    if permissions and permissions.get("unreadable_inputs"):
        missing.append("input devices")
    return " and ".join(missing) or None


def banner_text(engine: Any, permissions: dict, config_error: str | None) -> tuple[str, bool] | None:
    """``(text, offer_start)`` for the most important problem, or None when all is well."""
    if engine is None:
        return BANNER_NO_ENGINE, False
    state = engine.state
    if state == engine_states.STATE_EVDEV_MISSING:
        return BANNER_EVDEV, False
    if state == engine_states.STATE_STARTING:
        return BANNER_STARTING, False
    if state != engine_states.STATE_RUNNING:
        reason = f" ({engine.last_error})" if engine.last_error else ""
        return BANNER_DOWN.format(reason=reason), True
    what = _permission_problem(permissions)
    if what is not None:
        return BANNER_PERMISSIONS.format(what=what), False
    if config_error:
        return BANNER_CONFIG.format(error=config_error), False
    return None


def state_label(state: Any) -> str:
    """UI label for an engine device state."""
    return STATE_LABELS.get(state, str(state))
