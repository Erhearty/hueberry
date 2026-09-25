# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Application bootstrap for Hueberry.

openrazer is imported lazily by the backend, so this module stays importable
(and the app starts, showing an empty state) without python3-openrazer.
"""

import logging
import sys

from PyQt6.QtCore import QThreadPool
from PyQt6.QtWidgets import QApplication

from hueberry.backend.daemon import DaemonService
from hueberry.ui.main_window import MainWindow

APP_NAME = "Hueberry"
CONNECT_LABEL = "Connect"
EXIT_OK = 0
SHUTDOWN_WAIT_MS = 5000  # longest wait for background tasks on quit
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    """Run Hueberry and return a process exit code.

    :param argv: command-line arguments (without the program name); defaults
        to ``sys.argv``.
    :return: the Qt event loop's exit code (``EXIT_OK`` on a normal quit).
    """
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    logger.info("Hueberry starting")
    qt_argv = list(sys.argv) if argv is None else [sys.argv[0] if sys.argv else APP_NAME, *argv]
    app = QApplication(qt_argv)
    app.setApplicationName(APP_NAME)
    service = DaemonService()
    window = MainWindow(service)
    window.show()
    # Connecting may block on D-Bus, so it runs through worker.run_async and
    # the window reloads its device list when it completes.
    window.run_service_action(CONNECT_LABEL, service.connect)
    exit_code = app.exec()
    # Let in-flight D-Bus/daemon tasks finish before interpreter teardown.
    QThreadPool.globalInstance().waitForDone(SHUTDOWN_WAIT_MS)
    return exit_code
