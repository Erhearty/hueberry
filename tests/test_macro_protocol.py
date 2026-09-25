# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Tests for the macro engine IPC protocol and client."""

import errno
import json
import socket
from pathlib import Path

import pytest

from hueberry.macros import protocol
from hueberry.macros.protocol import (
    EngineClient,
    EngineError,
    EngineUnavailable,
    LineBuffer,
    ProtocolError,
)


def test_socket_path_prefers_xdg_runtime_dir(monkeypatch):
    """The socket lives under $XDG_RUNTIME_DIR/hueberry."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1234")
    assert protocol.socket_path() == Path("/run/user/1234/hueberry/macro-engine.sock")


def test_socket_path_falls_back_to_uid(monkeypatch):
    """Without $XDG_RUNTIME_DIR the path uses /run/user/<uid>."""
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setattr(protocol.os, "getuid", lambda: 42)
    assert protocol.socket_path() == Path("/run/user/42/hueberry/macro-engine.sock")


def test_request_round_trip():
    """encode -> decode preserves op and args."""
    line = protocol.encode(protocol.request_message("record_start", identity="1532:0001:x:y"))
    assert line.endswith(b"\n") and line.count(b"\n") == 1
    assert protocol.decode(line.rstrip(b"\n")) == {
        "op": "record_start", "args": {"identity": "1532:0001:x:y"},
    }


def test_decode_defaults_args():
    """A request without args decodes with empty args."""
    assert protocol.decode(b'{"op":"ping"}') == {"op": "ping", "args": {}}


@pytest.mark.parametrize("line", [
    b"not json",
    b"\xff\xfe",
    b"[1, 2]",
    b'{"op": "shell"}',
    b'{"op": 5}',
    b'{"args": {}}',
    b'{"op": "ping", "args": []}',
])
def test_decode_rejects_garbage_and_unknown_ops(line):
    """Malformed JSON, non-objects and unknown ops are protocol errors."""
    with pytest.raises(ProtocolError):
        protocol.decode(line)


def test_decode_rejects_oversize_line():
    """Lines longer than MAX_LINE_BYTES are rejected before parsing."""
    with pytest.raises(ProtocolError):
        protocol.decode(b" " * (protocol.MAX_LINE_BYTES + 1))


def test_encode_rejects_oversize_message():
    """The sender refuses messages the receiver would reject."""
    with pytest.raises(ProtocolError):
        protocol.encode({"op": "ping", "args": {"x": "a" * protocol.MAX_LINE_BYTES}})


def test_line_buffer_splits_and_bounds():
    """Partial lines are kept; overlong pending data raises."""
    buffer = LineBuffer()
    assert buffer.feed(b'{"a":1}\n{"b"') == [b'{"a":1}']
    assert buffer.feed(b":2}\n") == [b'{"b":2}']
    with pytest.raises(ProtocolError):
        buffer.feed(b"x" * (protocol.MAX_LINE_BYTES + 1))


def _pair_client(reply: bytes | None):
    """A client wired to one socketpair end; ``reply`` is pre-queued on the other."""
    client_end, server_end = socket.socketpair()
    if reply is not None:
        server_end.sendall(reply)
    client = EngineClient(Path("/unused"), connect=lambda path, timeout: client_end, timeout=1.0)
    return client, server_end


def test_client_returns_result_and_sends_request():
    """request() sends one line and returns the reply's result."""
    client, server_end = _pair_client(protocol.encode(protocol.ok_response({"pong": True})))
    try:
        assert client.request("ping") == {"pong": True}
        sent = server_end.recv(protocol.RECV_CHUNK_BYTES)
        assert json.loads(sent) == {"op": "ping", "args": {}}
    finally:
        server_end.close()


def test_client_raises_engine_error_on_failure_reply():
    """{ok: false} becomes EngineError with the engine's message."""
    client, server_end = _pair_client(protocol.encode(protocol.error_response("nope")))
    try:
        with pytest.raises(EngineError, match="nope"):
            client.request("status")
    finally:
        server_end.close()


def test_client_raises_engine_error_on_garbage_reply():
    """An unreadable reply is an EngineError, not a crash."""
    client, server_end = _pair_client(b"garbage\n")
    try:
        with pytest.raises(EngineError):
            client.request("status")
    finally:
        server_end.close()


def test_client_unavailable_when_peer_closes():
    """EOF before a reply means the engine is unavailable."""
    client, server_end = _pair_client(None)
    server_end.close()
    with pytest.raises(EngineUnavailable):
        client.request("ping")


def test_client_unavailable_on_timeout():
    """No reply within the timeout maps to EngineUnavailable."""
    client_end, server_end = socket.socketpair()
    client_end.settimeout(0)  # non-blocking: recv raises immediately instead of waiting
    client = EngineClient(Path("/unused"), connect=lambda path, timeout: client_end)
    try:
        with pytest.raises(EngineUnavailable):
            client.request("ping")
    finally:
        server_end.close()


@pytest.mark.parametrize("error", [
    FileNotFoundError(errno.ENOENT, "No such file"),
    ConnectionRefusedError(errno.ECONNREFUSED, "Connection refused"),
    socket.timeout("timed out"),
])
def test_client_unavailable_on_connect_errors(error):
    """ENOENT / ECONNREFUSED / timeout while connecting map to EngineUnavailable."""
    def _connect(path, timeout):
        raise error

    with pytest.raises(EngineUnavailable):
        EngineClient(Path("/unused"), connect=_connect).request("ping")


def test_client_real_socket_missing(tmp_path):
    """The default connector reports a missing socket as EngineUnavailable."""
    with pytest.raises(EngineUnavailable):
        EngineClient(tmp_path / "missing.sock", timeout=0.5).request("ping")
