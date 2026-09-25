# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""The engine's listening Unix socket: private permissions, single instance.

A second engine must never take over devices from a running one, so an
existing socket is probed first and only removed when connecting to it is
refused or it does not exist (left behind by a crash). Any other outcome -
including a connect that succeeds but a peer that is slow to answer - means
somebody is listening, so we refuse to take over.
"""

import errno
import logging
import os
import socket
from pathlib import Path
from typing import Any, Callable

from hueberry.macros import protocol

logger = logging.getLogger(__name__)

SOCKET_DIR_MODE = 0o700
SOCKET_MODE = 0o600
LISTEN_BACKLOG = 8
PROBE_TIMEOUT_S = 0.5
STALE_SOCKET_ERRNOS = frozenset({errno.ENOENT, errno.ECONNREFUSED})


class AlreadyRunning(RuntimeError):
    """Another engine answers on the socket; this one must not take over."""


def probe_engine(path: Path, connect: Callable[[Path, float], Any] = protocol.connect_unix) -> bool:
    """True unless the socket at ``path`` is provably stale (ENOENT/ECONNREFUSED).

    A successful connect counts as running without waiting for a reply, so a
    busy engine is never mistaken for a dead one.
    """
    try:
        sock = connect(path, PROBE_TIMEOUT_S)
    except OSError as exc:
        return exc.errno not in STALE_SOCKET_ERRNOS
    sock.close()
    return True


def ensure_socket_dir(directory: Path) -> None:
    """Create ``directory`` 0700; only tighten an existing one if it is our default dir.

    An arbitrary existing parent (e.g. a user-chosen ``--socket`` location)
    is never chmodded.
    """
    try:
        directory.mkdir(mode=SOCKET_DIR_MODE, parents=True)
    except FileExistsError:
        if directory != protocol.socket_path().parent:
            return
    os.chmod(directory, SOCKET_DIR_MODE)


def prepare_socket(path: Path, probe: Callable[[Path], bool] = probe_engine) -> socket.socket:
    """Bind a non-blocking listening socket (dir 0700, socket 0600), clearing a stale one.

    Raises AlreadyRunning when an existing socket still answers.
    """
    ensure_socket_dir(path.parent)
    if path.exists():
        if probe(path):
            raise AlreadyRunning(f"a macro engine is already running on {path}")
        logger.info("Removing stale socket %s", path)
        path.unlink(missing_ok=True)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind(str(path))
        os.chmod(path, SOCKET_MODE)
        sock.listen(LISTEN_BACKLOG)
        sock.setblocking(False)
    except BaseException:
        sock.close()
        raise
    return sock
