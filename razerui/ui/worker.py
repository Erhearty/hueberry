# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 RazerUI contributors
"""Run blocking backend calls on the global QThreadPool.

Panels call ``worker.run_async(...)`` through the *module attribute* (``from
razerui.ui import worker``) rather than importing the function, so tests can
monkeypatch :func:`run_async` with a synchronous stand-in.
"""

import functools
import logging
from typing import Any, Callable

from PyQt6 import sip
from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

logger = logging.getLogger(__name__)

# Tasks still running; holding them keeps their WorkerSignals alive until the
# completion signal has been delivered.
_pending: set["Task"] = set()


class WorkerSignals(QObject):
    """Signals of a :class:`Task`: ``finished(result)`` or ``failed(message)``."""

    finished = pyqtSignal(object)
    failed = pyqtSignal(str)


class Task(QRunnable):
    """A QRunnable calling ``fn()`` and reporting through :attr:`signals`."""

    def __init__(self, fn: Callable[[], Any]) -> None:
        super().__init__()
        self._fn = fn
        self.signals = WorkerSignals()

    def run(self) -> None:
        """Call the function; any exception becomes ``failed(str(exc))``."""
        try:
            result = self._fn()
        except Exception as exc:  # report every failure to the GUI thread
            logger.warning("Background task failed", exc_info=True)
            self.signals.failed.emit(str(exc) or type(exc).__name__)
            return
        self.signals.finished.emit(result)


def ignore_deleted(method: Callable[..., Any]) -> Callable[..., Any]:
    """Decorate a QObject callback method so it is skipped once the object is deleted.

    A background task can finish after its widget was destroyed; the callback
    then must not touch the dead C++ object (PyQt raises RuntimeError).
    """

    @functools.wraps(method)
    def wrapper(self: QObject, *args: Any) -> Any:
        if sip.isdeleted(self):
            logger.info("Skipping %s: widget was deleted", method.__qualname__)
            return None
        try:
            return method(self, *args)
        except RuntimeError:  # the object died while the callback ran
            logger.warning("Callback %s failed on a deleted object", method.__qualname__,
                           exc_info=True)
            return None

    return wrapper


def _forget(task: Task) -> None:
    _pending.discard(task)


def run_async(
    fn: Callable[[], Any],
    on_done: Callable[[Any], None] | None = None,
    on_error: Callable[[str], None] | None = None,
) -> Task:
    """Run ``fn`` on ``QThreadPool.globalInstance()``.

    ``on_done(result)`` or ``on_error(message)`` is invoked on the thread that
    owns the callback (the GUI thread for widget slots). Returns the Task.
    """
    task = Task(fn)
    _pending.add(task)
    if on_done is not None:
        task.signals.finished.connect(on_done)
    if on_error is not None:
        task.signals.failed.connect(on_error)
    task.signals.finished.connect(lambda _result: _forget(task))
    task.signals.failed.connect(lambda _message: _forget(task))
    QThreadPool.globalInstance().start(task)
    return task
