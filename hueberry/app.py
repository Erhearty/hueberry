# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Application bootstrap for Hueberry.

openrazer is imported lazily by the backend, so this module stays importable
(and the app starts, showing an empty state) without python3-openrazer.
Only one Hueberry runs per user: a second launch shows the first one's window
and exits. With a system tray, closing the window keeps Hueberry (and the
macro engine) running; ``--background`` starts with the tray icon only.
"""

import logging
import sys

from PyQt6.QtCore import QThreadPool
from PyQt6.QtWidgets import QApplication

from hueberry.backend import animator
from hueberry.backend.daemon import DaemonService
from hueberry.backend.macro_engine import MacroEngineService
from hueberry.settings import Settings
from hueberry.single_instance import SingleInstance
from hueberry.ui.main_window import MainWindow
from hueberry.ui.theme import apply_theme
from hueberry.ui.tray import TrayController

APP_NAME = "Hueberry"
CONNECT_LABEL = "Connect"
BACKGROUND_FLAG = "--background"
EXIT_OK = 0
SHUTDOWN_WAIT_MS = 5000  # longest wait for background tasks on quit
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

logger = logging.getLogger(__name__)


def split_args(argv: list[str] | None) -> tuple[list[str], bool]:
    """Return ``(qt_argv, background)``: ``--background`` is ours, the rest goes to Qt."""
    program = sys.argv[0] if sys.argv else APP_NAME
    args = list(sys.argv[1:]) if argv is None else list(argv)
    background = BACKGROUND_FLAG in args
    return [program, *(arg for arg in args if arg != BACKGROUND_FLAG)], background


def _build_window(app: QApplication, tray: TrayController) -> tuple[MainWindow, DaemonService]:
    """Create the services and window and wire quit/stop handling."""
    service = DaemonService()
    engine = MacroEngineService()
    window = MainWindow(service, engine=engine, tray=tray)
    tray.quit_requested.connect(app.quit)
    window.quit_requested.connect(app.quit)
    # The engine holds device grabs: stop it before anything else is torn down.
    app.aboutToQuit.connect(engine.stop)
    app.aboutToQuit.connect(tray.hide)
    return window, service


def _stop_animations_on_quit(app: QApplication) -> None:
    """Stop (and restore) preset animations when Qt is about to quit."""
    about_to_quit = getattr(app, "aboutToQuit", None)
    if about_to_quit is None:  # not a real QApplication
        logger.warning("Application has no aboutToQuit signal; animations not bound")
        return
    about_to_quit.connect(animator.shared_animator().shutdown)


def main(argv: list[str] | None = None) -> int:
    """Run Hueberry and return a process exit code.

    :param argv: command-line arguments (without the program name); defaults
        to ``sys.argv``.
    :return: the Qt event loop's exit code (``EXIT_OK`` on a normal quit).
    """
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    qt_argv, background = split_args(argv)
    app = QApplication(qt_argv)
    app.setApplicationName(APP_NAME)
    instance = SingleInstance()
    if instance.notify_or_listen(show=not background):
        return EXIT_OK
    logger.info("Hueberry starting (background=%s)", background)
    apply_theme(app)
    tray = TrayController(Settings())
    if tray.available:
        app.setQuitOnLastWindowClosed(False)
    window, service = _build_window(app, tray)
    instance.show_requested.connect(window.show_and_raise)
    if background and tray.available:
        logger.info("Starting in the background (tray only)")
    else:
        window.show()
    window.start_engine()
    # Connecting may block on D-Bus, so it runs through worker.run_async and
    # the window reloads its device list when it completes.
    window.run_service_action(CONNECT_LABEL, service.connect)
    _stop_animations_on_quit(app)
    exit_code = app.exec()
    # Let in-flight D-Bus/daemon tasks finish before interpreter teardown.
    QThreadPool.globalInstance().waitForDone(SHUTDOWN_WAIT_MS)
    instance.close()
    return exit_code
