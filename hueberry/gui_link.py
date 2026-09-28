# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Qt-free client side of the GUI's single-instance socket.

The macro engine (which must stay free of any GUI toolkit) uses this to ask a running
Hueberry window to perform one of a small, allow-listed set of app actions.
Only the action name ever travels over the socket, and only the action name
is ever logged.
"""

import logging
import os
import socket
from pathlib import Path

logger = logging.getLogger(__name__)

RUNTIME_DIR_FALLBACK = "/run/user/{uid}"
SOCKET_DIR_NAME = "hueberry"
SOCKET_FILE_NAME = "gui.sock"
SEND_TIMEOUT_S = 0.5
MESSAGE_TERMINATOR = "\n"

APP_ACTION_TOGGLE_SYSMON = "toggle-sysmon"
APP_ACTIONS = (APP_ACTION_TOGGLE_SYSMON,)
APP_ACTION_LABELS = {APP_ACTION_TOGGLE_SYSMON: "Toggle system monitor"}


def default_server_name() -> str:
    """Absolute socket path in the per-user runtime dir (private, tmpfs)."""
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR") or RUNTIME_DIR_FALLBACK.format(uid=os.getuid())
    return str(Path(runtime_dir) / SOCKET_DIR_NAME / SOCKET_FILE_NAME)


def action_message(action: str) -> bytes:
    """Wire form of ``action``; raises ValueError for anything not in APP_ACTIONS."""
    if action not in APP_ACTIONS:
        raise ValueError(f"unknown app action {action!r}")
    return (action + MESSAGE_TERMINATOR).encode()


def send_message(payload: bytes, path: str | None = None, timeout_s: float = SEND_TIMEOUT_S) -> bool:
    """Send ``payload`` to the GUI socket at ``path`` (default: the instance socket).

    Returns False (after logging a warning without the payload) when no GUI
    is listening or the write fails; True once the bytes were sent.
    """
    target = path if path is not None else default_server_name()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(timeout_s)
            client.connect(target)
            client.sendall(payload)
    except OSError as exc:
        logger.warning("Could not reach the Hueberry window at %s: %s", target, exc)
        return False
    return True


def send_action(action: str) -> bool:
    """Ask the running GUI to perform the allow-listed ``action``."""
    return send_message(action_message(action))
