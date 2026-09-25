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
        self._poll_interval = poll_interval
        self._selector = selectors.DefaultSelector()
        self._listener: socket.socket | None = None
        self._owns_socket = False
        self._handles: dict[str, DeviceHandle] = {}
        self._states: dict[str, dict] = {}
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
        for identity in list(self._handles):
            try:
                self._detach(identity)
            except Exception:  # keep releasing the remaining devices
                logger.exception("Failed to release %s", identity)
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

    def _read_device(self, _fileobj: Any, identity: str) -> None:
        handle = self._handles.get(identity)
        if handle is None:
            return
        try:
            events = list(handle.device.read())
        except BlockingIOError:
            return
        except OSError as exc:  # unplugged
            logger.warning("Device %r lost: %s", handle.name, exc)
            self._states[identity] = {"name": handle.name, "state": "disconnected", "error": str(exc)}
            self._detach(identity)
            return
        for event in events:
            if self._recorder is not None and self._recorder.identity == identity:
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
        listed = [{"identity": e.identity, "path": e.path, "name": e.name, "has_keys": e.has_keys,
                   "state": self._states.get(e.identity, {}).get("state")} for e in self._discover()]
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
        if identity not in self._handles:
            self._open_for_recording(identity)
        self._recorder = self._recorder_factory(identity)
        return {"identity": identity}

    def _open_for_recording(self, identity: str) -> None:
        entry = next((e for e in self._discover() if e.identity == identity), None)
        if entry is None:
            raise CommandError(f"device not found: {identity}")
        try:
            self._attach(entry)  # not grabbed: recording only listens
        except OSError as exc:
            raise CommandError(f"cannot open {entry.path}: {exc}") from exc

    def _op_record_stop(self, _args: dict) -> dict:
        recorder, self._recorder = self._recorder, None
        if recorder is None:
            raise CommandError("not recording")
        self._release_if_unused(recorder.identity)
        return {"identity": recorder.identity, "events": recorder.stop(), "truncated": recorder.truncated}

    # -- devices ---------------------------------------------------------------

    def reload(self) -> None:
        """Re-read macros.json, stop every remapper and rebuild from scratch."""
        config, self.config_error = self._load_config()
        for identity in list(self._handles):
            self._stop_remapper(identity)
        self._states.clear()
        wanted = {entry.identity: entry for entry in config.devices if entry.enabled_macros()}
        if not wanted:
            return
        for entry in self._discover():
            if entry.identity in wanted:
                self._start_remapper(entry, wanted[entry.identity].enabled_macros())

    def _attach(self, entry: Any) -> DeviceHandle:
        device = self._open_device(entry.path)
        try:
            self._selector.register(device, selectors.EVENT_READ, (KIND_DEVICE, entry.identity))
        except (OSError, ValueError):
            device.close()
            raise
        handle = DeviceHandle(entry.identity, entry.name, device)
        self._handles[entry.identity] = handle
        return handle

    def _detach(self, identity: str) -> None:
        handle = self._handles.pop(identity, None)
        if handle is None:
            return
        if handle.remapper is not None:
            handle.remapper.stop()
        try:
            self._selector.unregister(handle.device)
        except (KeyError, ValueError, OSError) as exc:
            logger.debug("Unregister of %s failed: %s", identity, exc)
        try:
            handle.device.close()
        except OSError as exc:
            logger.warning("Closing %r failed: %s", handle.name, exc)

    def _release_if_unused(self, identity: str) -> None:
        handle = self._handles.get(identity)
        if handle is None:
            return
        remapping = handle.remapping
        recording = self._recorder is not None and self._recorder.identity == identity
        if not remapping and not recording:
            self._detach(identity)

    def _stop_remapper(self, identity: str) -> None:
        handle = self._handles[identity]
        if handle.remapper is not None:
            handle.remapper.stop()
            handle.remapper = None
        self._release_if_unused(identity)

    def _record_state(self, identity: str, name: str, remapper: Any) -> None:
        self._states[identity] = {"name": name, "state": remapper.state, "error": remapper.error}

    def _settle(self, handle: DeviceHandle) -> None:
        """Retry a deferred grab, record the remapper state, close the device if unused."""
        handle.retry_grab()
        self._record_state(handle.identity, handle.name, handle.remapper)
        self._release_if_unused(handle.identity)

    def _start_remapper(self, entry: Any, macros: list) -> None:
        existing = self._handles.get(entry.identity)
        if existing is not None and existing.remapper is not None:
            return  # duplicate node for the same identity
        try:
            handle = existing or self._attach(entry)
        except OSError as exc:
            self._states[entry.identity] = {"name": entry.name, "state": state_for_error(exc), "error": str(exc)}
            logger.warning("Cannot open %s: %s", entry.path, exc)
            return
        handle.remapper = self._remapper_factory(handle.device, macros)
        handle.remapper.start()
        self._record_state(entry.identity, entry.name, handle.remapper)
        self._release_if_unused(entry.identity)
