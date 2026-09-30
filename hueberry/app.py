# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Application bootstrap for Hueberry.

openrazer is imported lazily by the backend, so this module stays importable
(and the app starts, showing an empty state) without python3-openrazer.
Only one Hueberry runs per user: a second launch shows the first one's window
and exits. With a system tray, closing the window keeps Hueberry (and the
macro engine) running; ``--background`` starts with the tray icon only.
``--toggle-sysmon`` toggles the running Hueberry's system monitor overlay
(without raising its window); with no Hueberry running it starts one in the
background with the overlay switched on.
"""

import logging
import sys

from PyQt6.QtCore import QThreadPool
from PyQt6.QtWidgets import QApplication

from hueberry.backend import advanced_runtime
from hueberry.backend.daemon import DaemonService
from hueberry.backend.macro_engine import MacroEngineService
from hueberry.settings import Settings
from hueberry.single_instance import TOGGLE_SYSMON_MESSAGE, SingleInstance
from hueberry.sysmon.controller import SysmonController
from hueberry.ui.main_window import MainWindow
from hueberry.ui.theme import apply_theme
from hueberry.ui.wheel_guard import install as install_wheel_guard
from hueberry.ui.tray import TrayController

APP_NAME = "Hueberry"
CONNECT_LABEL = "Connect"
BACKGROUND_FLAG = "--background"
TOGGLE_SYSMON_FLAG = "--toggle-sysmon"
OWN_FLAGS = (BACKGROUND_FLAG, TOGGLE_SYSMON_FLAG)
EXIT_OK = 0
SHUTDOWN_WAIT_MS = 5000  # longest wait for background tasks on quit
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

logger = logging.getLogger(__name__)


def split_args(argv: list[str] | None) -> tuple[list[str], bool, bool]:
    """Return ``(qt_argv, background, toggle_sysmon)``.

    ``--background`` and ``--toggle-sysmon`` are ours; the rest goes to Qt.
    """
    program = sys.argv[0] if sys.argv else APP_NAME
    args = list(sys.argv[1:]) if argv is None else list(argv)
    background = BACKGROUND_FLAG in args
    toggle_sysmon = TOGGLE_SYSMON_FLAG in args
    qt_argv = [program, *(arg for arg in args if arg not in OWN_FLAGS)]
    return qt_argv, background, toggle_sysmon


def _build_window(
    app: QApplication, tray: TrayController
) -> tuple[MainWindow, DaemonService, SysmonController]:
    """Create the services, sysmon controller and window; wire quit/stop handling."""
    service = DaemonService()
    engine = MacroEngineService()
    sysmon = SysmonController()
    # With ``sysmon`` the window wires the tray's sysmon action itself.
    window = MainWindow(service, engine=engine, tray=tray, sysmon=sysmon)
    tray.quit_requested.connect(app.quit)
    window.quit_requested.connect(app.quit)
    # The engine holds device grabs: stop it before anything else is torn down.
    app.aboutToQuit.connect(engine.stop)
    app.aboutToQuit.connect(sysmon.shutdown)
    app.aboutToQuit.connect(tray.hide)
    return window, service, sysmon


def _notify_running(instance: SingleInstance, background: bool, toggle_sysmon: bool) -> bool:
    """Hand the launch to a running Hueberry; True when the caller should exit.

    With ``--toggle-sysmon`` the running one only toggles its overlay (its
    window is not raised); otherwise it is asked to show unless ``background``.
    """
    if toggle_sysmon:
        return instance.notify_or_listen(show=False, message=TOGGLE_SYSMON_MESSAGE)
    return instance.notify_or_listen(show=not background)


def _start_sysmon(instance: SingleInstance, sysmon: SysmonController, switch_on: bool) -> None:
    """Restore the persisted overlay state and route toggle requests to ``sysmon``.

    ``switch_on`` (first launch with ``--toggle-sysmon``) turns the overlay on
    with ``start()`` rather than ``toggle()``: ``restore()`` may already have
    started it (``enabled=True``) and a toggle would then switch it off again.
    """
    instance.toggle_sysmon_requested.connect(sysmon.toggle)
    sysmon.restore()
    if switch_on:
        sysmon.start()  # no-op when restore() already started it


def _show_window(window: MainWindow, tray: TrayController, background: bool) -> None:
    """Show ``window`` unless starting in the background with a usable tray."""
    if background and tray.available:
        logger.info("Starting in the background (tray only)")
    else:
        window.show()


def _stop_animations_on_quit(app: QApplication) -> None:
    """Stop the per-key effect runtime when Qt is about to quit."""
    about_to_quit = getattr(app, "aboutToQuit", None)
    if about_to_quit is None:  # not a real QApplication
        logger.warning("Application has no aboutToQuit signal; animations not bound")
        return
    about_to_quit.connect(advanced_runtime.shared_runtime().shutdown)


def main(argv: list[str] | None = None) -> int:
    """Run Hueberry and return a process exit code.

    :param argv: command-line arguments (without the program name); defaults
        to ``sys.argv``.
    :return: the Qt event loop's exit code (``EXIT_OK`` on a normal quit).
    """
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    qt_argv, background, toggle_sysmon = split_args(argv)
    app = QApplication(qt_argv)
    app.setApplicationName(APP_NAME)
    instance = SingleInstance()
    if _notify_running(instance, background, toggle_sysmon):
        return EXIT_OK
    background = background or toggle_sysmon
    logger.info("Hueberry starting (background=%s)", background)
    apply_theme(app)
    install_wheel_guard(app)
    tray = TrayController(Settings())
    if tray.available:
        app.setQuitOnLastWindowClosed(False)
    window, service, sysmon = _build_window(app, tray)
    instance.show_requested.connect(window.show_and_raise)
    _show_window(window, tray, background)
    window.start_engine()
    _start_sysmon(instance, sysmon, toggle_sysmon)
    # Connecting may block on D-Bus, so it runs through worker.run_async and
    # the window reloads its device list when it completes.
    window.run_service_action(CONNECT_LABEL, service.connect)
    _stop_animations_on_quit(app)
    exit_code = app.exec()
    # Let in-flight D-Bus/daemon tasks finish before interpreter teardown.
    QThreadPool.globalInstance().waitForDone(SHUTDOWN_WAIT_MS)
    instance.close()
    return exit_code
