# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""The engine's single-threaded event loop: IPC socket, devices, parent watch.

One ``selectors`` loop multiplexes the listening socket, client
connections, every opened input device, a self-pipe for signal wakeups and
(when available) a pidfd of the parent. Keeping everything on one thread
means grabs are only ever changed from here, so ``close()`` can release
every device deterministically whatever made the loop stop.
"""

import logging
import os
import selectors
import socket
from pathlib import Path
from typing import Any, Callable

from hueberry.macro_engine import devices
from hueberry.macro_engine.handles import DeviceHandle
from hueberry.macro_engine.listener import AlreadyRunning, prepare_socket, probe_engine  # noqa: F401 - re-export
from hueberry.macro_engine.nodes import (
    STATE_DISCONNECTED,
    aggregate_states,
    attach_missing,
    close_handle,
    device_rows,
    engine_grabs,
    node_state,
    open_handle,
    paths_of,
    probe_nodes,
    remapper_state,
    wanted_entries,
)
from hueberry.macro_engine.recorder import Recorder
from hueberry.macro_engine.remapper import DeviceRemapper, state_for_error
from hueberry.macros import protocol, store

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 1.0
CLIENT_IO_TIMEOUT_S = 1.0
WAKE_BYTE = b"\0"
WAKE_DRAIN_BYTES = 512
KIND_LISTENER = "listener"
KIND_CLIENT = "client"
KIND_DEVICE = "device"
KIND_PARENT = "parent"
KIND_WAKEUP = "wakeup"
MSG_INTERNAL_ERROR = "internal engine error; see the engine log"
MSG_GRABBED_EXCLUSIVELY = ("device is grabbed exclusively by another program (e.g. keyd or OpenRazer macro mode); "
                           "exclude it there (keyd: add -<vendor>:<product> under [ids]) and retry")


class CommandError(ValueError):
    """A well-formed request that cannot be carried out (sent back as an error)."""


class EngineServer:
    """Serves protocol requests and drives remappers/recorder for opened devices.

    Collaborators are injectable for tests; ``parent_watcher`` needs
    ``fileno() -> int | None`` (readable when the parent exits) and ``alive()``.
    """

    def __init__(
        self,
        path: Path,
        *,
        parent_watcher: Any = None,
        load_config: Callable[[], tuple] = store.load,
        discover: Callable[[], list] = devices.discover,
        open_device: Callable[[str], Any] = devices.open_device,
        check_permissions: Callable[[], Any] = devices.check_permissions,
        remapper_factory: Callable[..., Any] = DeviceRemapper,
        recorder_factory: Callable[[str], Any] = Recorder,
        probe: Callable[[Path], bool] = probe_engine,
        probe_grab: Callable[[Any], bool] = devices.probe_foreign_grab,
        poll_interval: float = POLL_INTERVAL_S,
    ) -> None:
        self.path = Path(path)
        self._watcher = parent_watcher
        self._load_config = load_config
        self._discover = discover
        self._open_device = open_device
        self._check_permissions = check_permissions
        self._remapper_factory = remapper_factory
        self._recorder_factory = recorder_factory
        self._probe = probe
        self._probe_grab = probe_grab
        self._poll_interval = poll_interval
        self._selector = selectors.DefaultSelector()
        self._listener: socket.socket | None = None
        self._owns_socket = False
        self._handles: dict[str, DeviceHandle] = {}  # keyed by node path
        self._node_states: dict[str, dict] = {}  # keyed by node path, see nodes.node_state
        self._recorder: Any = None
        self._stopping = False
        self._closed = False
        self.stop_reason: str | None = None
        self.config_error: str | None = None
        self._wake_r, self._wake_w = os.pipe()
        os.set_blocking(self._wake_r, False)
        os.set_blocking(self._wake_w, False)
        self._handlers = {op: getattr(self, f"_op_{op}") for op in protocol.KNOWN_OPS}
        self._ready_handlers = {
            KIND_LISTENER: self._accept, KIND_CLIENT: self._serve_client,
            KIND_DEVICE: self._read_device, KIND_PARENT: self._parent_exited, KIND_WAKEUP: self._drain_wakeup,
        }

    @property
    def _states(self) -> dict[str, dict]:
        """Per-identity ``{name, state, error}``, folded from the node states."""
        return aggregate_states(self._node_states)

    # -- lifecycle -----------------------------------------------------------

    def setup(self) -> None:
        """Bind the socket, register wakeup/parent fds and apply the config."""
        self._listener = prepare_socket(self.path, self._probe)
        self._owns_socket = True
        self._selector.register(self._listener, selectors.EVENT_READ, (KIND_LISTENER, None))
        self._selector.register(self._wake_r, selectors.EVENT_READ, (KIND_WAKEUP, None))
        parent_fd = self._watcher.fileno() if self._watcher is not None else None
        if parent_fd is not None:
            self._selector.register(parent_fd, selectors.EVENT_READ, (KIND_PARENT, None))
        self.reload()
        logger.info("Macro engine listening on %s", self.path)

    def serve(self) -> None:
        """setup + run, always followed by close (ungrab everything, remove socket)."""
        try:
            self.setup()
            self.run()
        finally:
            self.close()

    def run(self) -> None:
        """Loop until stopped, the parent dies or an exception escapes."""
        while not self._stopping:
            self.run_once(self._poll_interval)
            if not self._stopping and self._watcher is not None and not self._watcher.alive():
                self._request("parent process is gone")
        logger.info("Macro engine stopping: %s", self.stop_reason)

    def run_once(self, timeout: float | None) -> None:
        """Handle whatever is ready within ``timeout`` seconds, then retry deferred grabs."""
        for key, _mask in self._selector.select(timeout):
            kind, ref = key.data
            self._ready_handlers[kind](key.fileobj, ref)
        for handle in list(self._handles.values()):
            if handle.pending_grab:
                self._settle(handle)

    def _request(self, reason: str) -> None:
        if self.stop_reason is None:
            self.stop_reason = reason
        self._stopping = True

    def request_stop(self, reason: str = "stop requested") -> None:
        """Ask the loop to exit; async-signal-safe (flag + self-pipe byte)."""
        self._request(reason)
        try:
            os.write(self._wake_w, WAKE_BYTE)
        except BlockingIOError:
            pass  # pipe full: a wakeup is already pending
        except OSError as exc:  # already closed: the loop is gone anyway
            logger.debug("Wakeup write failed: %s", exc)

    def close(self) -> None:
        """Release every grab first, then clients, socket, selector and pipe."""
        if self._closed:
            return
        self._closed = True
        for path in list(self._handles):
            try:
                self._detach(path)
            except Exception:  # keep releasing the remaining devices
                logger.exception("Failed to release %s", path)
        self._recorder = None
        for key in list(self._selector.get_map().values()):
            if key.data[0] == KIND_CLIENT:
                key.fileobj.close()
        if self._listener is not None:
            self._listener.close()
        if self._owns_socket:
            self.path.unlink(missing_ok=True)
        self._selector.close()
        os.close(self._wake_r)
        os.close(self._wake_w)

    # -- ready handlers ------------------------------------------------------

    def _drain_wakeup(self, fileobj: Any, _ref: Any) -> None:
        try:
            while os.read(self._wake_r, WAKE_DRAIN_BYTES):
                pass
        except BlockingIOError:
            pass  # drained

    def _parent_exited(self, fileobj: Any, _ref: Any) -> None:
        self._selector.unregister(fileobj)
        self._request("parent process exited")

    def _accept(self, listener: Any, _ref: Any) -> None:
        try:
            conn, _addr = listener.accept()
        except BlockingIOError:
            return
        except OSError as exc:
            logger.warning("accept failed: %s", exc)
            return
        conn.settimeout(CLIENT_IO_TIMEOUT_S)
        self._selector.register(conn, selectors.EVENT_READ, (KIND_CLIENT, protocol.LineBuffer()))

    def _drop_client(self, conn: Any) -> None:
        try:
            self._selector.unregister(conn)
        except (KeyError, ValueError):
            pass  # already unregistered
        conn.close()

    def _reply(self, conn: Any, response: dict) -> bool:
        try:
            payload = protocol.encode(response)
        except protocol.ProtocolError as exc:
            payload = protocol.encode(protocol.error_response(str(exc)))
        try:
            conn.sendall(payload)
        except OSError as exc:
            logger.info("Client went away: %s", exc)
            self._drop_client(conn)
            return False
        return True

    def _serve_client(self, conn: Any, buffer: protocol.LineBuffer) -> None:
        try:
            data = conn.recv(protocol.RECV_CHUNK_BYTES)
        except OSError as exc:
            logger.info("Client read failed: %s", exc)
            data = b""
        if not data:
            self._drop_client(conn)
            return
        try:
            lines = buffer.feed(data)
        except protocol.ProtocolError as exc:
            if self._reply(conn, protocol.error_response(str(exc))):
                self._drop_client(conn)
            return
        for line in lines:
            if not self._reply(conn, self.handle_line(line)):
                return

    def _read_device(self, _fileobj: Any, path: str) -> None:
        handle = self._handles.get(path)
        if handle is None:
            return
        try:
            events = list(handle.device.read())
        except BlockingIOError:
            return
        except OSError as exc:  # unplugged
            logger.warning("Device %r lost: %s", handle.name, exc)
            self._node_states[path] = node_state(handle.identity, handle.name, STATE_DISCONNECTED, str(exc))
            self._detach(path)
            return
        for event in events:
            if self._recorder is not None and self._recorder.identity == handle.identity:
                self._recorder.handle(event)
            if handle.remapper is not None:
                handle.remapper.handle(event)
        if handle.remapper is not None:
            self._settle(handle)

    # -- requests --------------------------------------------------------------

    def handle_line(self, line: bytes) -> dict:
        """Decode one request line and return the reply dict (never raises)."""
        try:
            request = protocol.decode(line)
        except protocol.ProtocolError as exc:
            return protocol.error_response(str(exc))
        try:
            return protocol.ok_response(self._handlers[request["op"]](request["args"]))
        except CommandError as exc:
            return protocol.error_response(str(exc))
        except Exception:  # a bug must not kill the engine and leave devices grabbed
            logger.exception("Request %s failed", request["op"])
            return protocol.error_response(MSG_INTERNAL_ERROR)

    def _op_ping(self, _args: dict) -> dict:
        return {"pong": True, "pid": os.getpid()}

    def _op_status(self, _args: dict) -> dict:
        recording = self._recorder.identity if self._recorder is not None else None
        states = [{"identity": identity, **state} for identity, state in sorted(self._states.items())]
        return {"devices": states, "recording": recording, "config_error": self.config_error}

    def _op_list_devices(self, _args: dict) -> dict:
        report = self._check_permissions()
        listed = device_rows(self._discover(), self._states)
        permissions = {"uinput_ok": report.uinput_ok, "unreadable_inputs": list(report.unreadable_inputs)}
        return {"devices": listed, "permissions": permissions}

    def _op_reload(self, args: dict) -> dict:
        self.reload()
        return self._op_status(args)

    def _op_record_start(self, args: dict) -> dict:
        identity = args.get("identity")
        if not isinstance(identity, str):
            raise CommandError("record_start needs a string 'identity'")
        if self._recorder is not None:
            raise CommandError(f"already recording {self._recorder.identity}")
        self._open_for_recording(identity)
        blocked = self._refuse_foreign_grab(identity)
        self._recorder = self._recorder_factory(identity)
        return {"identity": identity, **({"blocked_nodes": blocked} if blocked else {})}

    def _open_for_recording(self, identity: str) -> None:
        """Attach every node of ``identity`` not open yet; fail only when none is usable."""
        entries = [e for e in self._discover() if e.identity == identity]
        if not entries:
            raise CommandError(f"device not found: {identity}")
        attach_missing(entries, self._handles, self._attach)  # not grabbed: recording only listens
        if not paths_of(self._handles, identity):
            raise CommandError(f"cannot open any node of {identity}; see the engine log")

    def _refuse_foreign_grab(self, identity: str) -> int:
        """Probe nodes we don't grab: all busy -> close them and refuse; else return the busy count."""
        probed, busy = probe_nodes(self._handles, identity, self._probe_grab)
        if probed and busy == probed and not engine_grabs(self._handles, identity):
            for path in paths_of(self._handles, identity):
                self._release_if_unused(path)
            raise CommandError(MSG_GRABBED_EXCLUSIVELY)
        if busy:
            logger.warning("Recording %s: %d of %d node(s) grabbed by another program", identity, busy, probed)
        return busy

    def _op_record_stop(self, _args: dict) -> dict:
        recorder, self._recorder = self._recorder, None
        if recorder is None:
            raise CommandError("not recording")
        for path in paths_of(self._handles, recorder.identity):
            self._release_if_unused(path)
        return {"identity": recorder.identity, "events": recorder.stop(), "truncated": recorder.truncated}

    # -- devices ---------------------------------------------------------------

    def reload(self) -> None:
        """Re-read macros.json, stop every remapper and rebuild from scratch."""
        config, self.config_error = self._load_config()
        for handle in list(self._handles.values()):
            if handle.remapper is not None:
                handle.remapper.stop()
                handle.remapper = None
            self._release_if_unused(handle.path)
        self._node_states.clear()
        for entry, macros in wanted_entries(config.devices, self._discover):
            self._start_remapper(entry, macros)

    def _attach(self, entry: Any) -> DeviceHandle:
        handle = open_handle(entry, self._open_device, self._selector, (KIND_DEVICE, entry.path))
        self._handles[entry.path] = handle
        return handle

    def _detach(self, path: str) -> None:
        handle = self._handles.pop(path, None)
        if handle is not None:
            close_handle(handle, self._selector)

    def _release_if_unused(self, path: str) -> None:
        handle = self._handles.get(path)
        if handle is None:
            return
        remapping = handle.remapping
        recording = self._recorder is not None and self._recorder.identity == handle.identity
        if not remapping and not recording:
            self._detach(path)

    def _settle(self, handle: DeviceHandle) -> None:
        """Retry a deferred grab, record the remapper state, close the device if unused."""
        handle.retry_grab()
        self._node_states[handle.path] = remapper_state(handle)
        self._release_if_unused(handle.path)

    def _start_remapper(self, entry: Any, macros: list) -> None:
        """Remap one node; nodes without any trigger end up inactive and closed."""
        try:
            handle = self._handles.get(entry.path) or self._attach(entry)
        except OSError as exc:
            self._node_states[entry.path] = node_state(entry.identity, entry.name, state_for_error(exc), str(exc))
            logger.warning("Cannot open %s: %s", entry.path, exc)
            return
        handle.remapper = self._remapper_factory(handle.device, macros)
        handle.remapper.start()
        self._node_states[handle.path] = remapper_state(handle)
        self._release_if_unused(entry.path)
