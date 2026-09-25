# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Newline-delimited JSON protocol between Hueberry and the macro engine.

A request is ``{"op": <op>, "args": {...}}``; a reply is either
``{"ok": true, "result": {...}}`` or ``{"ok": false, "error": "..."}``.
One JSON object per line keeps framing trivial and lets both sides bound
how much they buffer (``MAX_LINE_BYTES``) before a peer can exhaust memory.
"""

import json
import logging
import os
import socket
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

RUNTIME_DIR_FALLBACK = "/run/user/{uid}"
SOCKET_DIR_NAME = "hueberry"
SOCKET_FILE_NAME = "macro-engine.sock"
ENCODING = "utf-8"
NEWLINE = b"\n"
MAX_LINE_BYTES = 256 * 1024
RECV_CHUNK_BYTES = 4096
DEFAULT_TIMEOUT_S = 2.0

OP_PING = "ping"
OP_STATUS = "status"
OP_LIST_DEVICES = "list_devices"
OP_RELOAD = "reload"
OP_RECORD_START = "record_start"
OP_RECORD_STOP = "record_stop"
KNOWN_OPS = frozenset({OP_PING, OP_STATUS, OP_LIST_DEVICES, OP_RELOAD, OP_RECORD_START, OP_RECORD_STOP})


class ProtocolError(ValueError):
    """A line that is oversized, not JSON, or not a well-formed message."""


class EngineUnavailable(ConnectionError):
    """The engine is not running or did not answer in time."""


class EngineError(RuntimeError):
    """The engine answered, but reported a failure (or an unreadable reply)."""


def socket_path() -> Path:
    """Per-user socket path; the runtime dir is private to the user and tmpfs."""
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR") or RUNTIME_DIR_FALLBACK.format(uid=os.getuid())
    return Path(runtime_dir) / SOCKET_DIR_NAME / SOCKET_FILE_NAME


def encode(message: dict) -> bytes:
    """Serialise one message as a single line; refuses what a peer would reject."""
    data = json.dumps(message, separators=(",", ":"), ensure_ascii=True).encode(ENCODING)
    if len(data) + len(NEWLINE) > MAX_LINE_BYTES:
        raise ProtocolError(f"message exceeds {MAX_LINE_BYTES} bytes")
    return data + NEWLINE


def _parse_object(line: bytes) -> dict:
    if len(line) > MAX_LINE_BYTES:
        raise ProtocolError(f"line exceeds {MAX_LINE_BYTES} bytes")
    try:
        message = json.loads(line.decode(ENCODING))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"malformed JSON: {exc}") from exc
    if not isinstance(message, dict):
        raise ProtocolError("message is not a JSON object")
    return message


def decode(line: bytes) -> dict:
    """Parse and validate a request line; only known ops get past this point."""
    message = _parse_object(line)
    op = message.get("op")
    if not isinstance(op, str) or op not in KNOWN_OPS:
        raise ProtocolError(f"unknown op: {op!r}")
    args = message.get("args", {})
    if not isinstance(args, dict):
        raise ProtocolError("args must be a JSON object")
    return {"op": op, "args": args}


def decode_response(line: bytes) -> dict:
    """Parse a reply line; it must carry a boolean ``ok``."""
    message = _parse_object(line)
    if not isinstance(message.get("ok"), bool):
        raise ProtocolError("reply has no boolean 'ok'")
    return message


def request_message(op: str, **args: Any) -> dict:
    """Build a request dict."""
    return {"op": op, "args": args}


def ok_response(result: dict | None = None) -> dict:
    """Build a success reply."""
    return {"ok": True, "result": result or {}}


def error_response(message: str) -> dict:
    """Build a failure reply."""
    return {"ok": False, "error": message}


class LineBuffer:
    """Accumulates stream bytes and yields complete lines, bounded in size."""

    def __init__(self) -> None:
        self._pending = b""

    def feed(self, data: bytes) -> list[bytes]:
        """Add bytes; return finished lines. Raises ProtocolError when a line is too long."""
        self._pending += data
        *lines, self._pending = self._pending.split(NEWLINE)
        if len(self._pending) > MAX_LINE_BYTES or any(len(line) > MAX_LINE_BYTES for line in lines):
            self._pending = b""
            raise ProtocolError(f"line exceeds {MAX_LINE_BYTES} bytes")
        return [line for line in lines if line.strip()]


def connect_unix(path: Path, timeout: float) -> socket.socket:
    """Open a stream connection to ``path`` with ``timeout`` on every operation."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        sock.connect(str(path))
    except BaseException:
        sock.close()
        raise
    return sock


class EngineClient:
    """Blocking one-request-per-connection client for the macro engine.

    ``connect`` is injectable (``(path, timeout) -> socket``) so tests can hand
    in a socketpair end instead of a real Unix socket.
    """

    def __init__(
        self,
        path: Path | None = None,
        *,
        connect: Callable[[Path, float], Any] = connect_unix,
        timeout: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._path = path if path is not None else socket_path()
        self._connect = connect
        self._timeout = timeout

    def request(self, op: str, **args: Any) -> dict:
        """Send one request and return its ``result``.

        Raises EngineUnavailable when the engine cannot be reached or times out
        (callers treat that as "not running"), EngineError when it refuses.
        """
        payload = encode(request_message(op, **args))
        try:
            sock = self._connect(self._path, self._timeout)
        except OSError as exc:  # ENOENT, ECONNREFUSED, EACCES, timeout
            raise EngineUnavailable(f"macro engine not reachable at {self._path}: {exc}") from exc
        try:
            line = self._exchange(sock, payload)
        finally:
            sock.close()
        return self._result(line)

    def _exchange(self, sock: Any, payload: bytes) -> bytes:
        buffer = LineBuffer()
        try:
            sock.sendall(payload)
            while True:
                chunk = sock.recv(RECV_CHUNK_BYTES)
                if not chunk:
                    raise EngineUnavailable("macro engine closed the connection")
                lines = buffer.feed(chunk)
                if lines:
                    return lines[0]
        except ProtocolError as exc:
            raise EngineError(f"unreadable reply from macro engine: {exc}") from exc
        except OSError as exc:  # includes socket timeouts and resets
            raise EngineUnavailable(f"macro engine did not answer: {exc}") from exc

    @staticmethod
    def _result(line: bytes) -> dict:
        try:
            reply = decode_response(line)
        except ProtocolError as exc:
            raise EngineError(f"unreadable reply from macro engine: {exc}") from exc
        if not reply["ok"]:
            raise EngineError(str(reply.get("error") or "macro engine reported an error"))
        result = reply.get("result", {})
        return result if isinstance(result, dict) else {}
