# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Single-instance guard: a second launch asks the first to show its window.

The first Hueberry listens on a private local socket; a later launch connects
to it, sends ``show`` and exits. A socket left behind by a crashed instance
refuses connections and is removed before listening again; one that accepts
(another instance won the race) is left alone and notified instead.
"""

import logging
import os
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

logger = logging.getLogger(__name__)

RUNTIME_DIR_FALLBACK = "/run/user/{uid}"
SOCKET_DIR_NAME = "hueberry"
SOCKET_FILE_NAME = "gui.sock"
SOCKET_DIR_MODE = 0o700
SHOW_MESSAGE = b"show\n"
PING_MESSAGE = b"ping\n"  # probe only: detect a live instance without raising it
CONNECT_TIMEOUT_MS = 500
WRITE_TIMEOUT_MS = 500


def default_server_name() -> str:
    """Absolute socket path in the per-user runtime dir (private, tmpfs)."""
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR") or RUNTIME_DIR_FALLBACK.format(uid=os.getuid())
    return str(Path(runtime_dir) / SOCKET_DIR_NAME / SOCKET_FILE_NAME)


class SingleInstance(QObject):
    """Owns the instance socket; ``show_requested`` fires when another launch pings us."""

    show_requested = pyqtSignal()

    def __init__(self, name: str | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.name = name if name is not None else default_server_name()
        self._server: QLocalServer | None = None
        self._message = SHOW_MESSAGE

    def notify_or_listen(self, show: bool = True) -> bool:
        """True when another instance is running (the caller should exit).

        With ``show`` it is asked to show its window; without (``--background``)
        it is only probed. Otherwise start listening and return False.
        """
        self._message = SHOW_MESSAGE if show else PING_MESSAGE
        if self._listen() is None:
            logger.info("Hueberry is already running; asked it to show its window")
            return True
        return False

    def _notify_existing(self) -> bool:
        socket = QLocalSocket(self)
        socket.connectToServer(self.name)
        try:
            if not socket.waitForConnected(CONNECT_TIMEOUT_MS):
                return False
            socket.write(self._message)
            socket.waitForBytesWritten(WRITE_TIMEOUT_MS)
            socket.disconnectFromServer()
            return True
        finally:
            socket.deleteLater()

    def _listen(self) -> bool | None:
        """True when listening, False on error, None when a live instance owns the name.

        A live owner (it accepts our probe, which also asks it to show) is never
        removed; only a socket that refuses connections is stale. The probe runs
        before listen() too: with socket options set, Qt binds a temporary path
        and renames it over the name, which would silently replace a live socket.
        """
        if self._notify_existing():
            return None
        if self.name.startswith(os.sep):
            Path(self.name).parent.mkdir(mode=SOCKET_DIR_MODE, parents=True, exist_ok=True)
        server = QLocalServer(self)
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not server.listen(self.name):
            if self._notify_existing():
                logger.info("Another instance owns %s; not removing it", self.name)
                server.deleteLater()
                return None
            logger.info("Removing stale instance socket %s (%s)", self.name, server.errorString())
            QLocalServer.removeServer(self.name)
            if not server.listen(self.name):
                logger.warning("Cannot listen on %s: %s", self.name, server.errorString())
                return False
        server.newConnection.connect(self._on_connection)
        self._server = server
        return True

    def _on_connection(self) -> None:
        while self._server is not None and self._server.hasPendingConnections():
            connection = self._server.nextPendingConnection()
            connection.disconnected.connect(connection.deleteLater)
            connection.readyRead.connect(lambda conn=connection: self._on_message(conn))
            if connection.bytesAvailable():
                self._on_message(connection)

    def _on_message(self, connection: QLocalSocket) -> None:
        """Emit ``show_requested`` for a ``show`` message; a ``ping`` is ignored."""
        data = bytes(connection.readAll())
        connection.close()
        if data.startswith(SHOW_MESSAGE.strip()):
            self.show_requested.emit()

    def close(self) -> None:
        """Stop listening (removes the socket file)."""
        if self._server is not None:
            self._server.close()
            self._server = None
