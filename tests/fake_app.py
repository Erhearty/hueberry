# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Stand-ins for the collaborators of ``hueberry.app.main`` (no event loop, no tray)."""


class FakeSignal:
    """Records connected slots; ``emit`` calls them."""

    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)

    def emit(self, *args):
        for slot in list(self.slots):
            slot(*args)


class FakeApp:
    """Stands in for QApplication; ``exec`` emits aboutToQuit and returns 0."""

    created: list = []

    def __init__(self, argv):
        self.argv = argv
        self.name = None
        self.quit_on_last_window_closed = True
        self.aboutToQuit = FakeSignal()
        self.quit_calls = 0
        FakeApp.created.append(self)

    def setApplicationName(self, name):
        self.name = name

    def setQuitOnLastWindowClosed(self, value):
        self.quit_on_last_window_closed = value

    def quit(self):
        self.quit_calls += 1

    def exec(self):
        self.aboutToQuit.emit()
        return 0


class FakeWindow:
    """Stands in for MainWindow; records show(), engine start and service actions."""

    created: list = []

    def __init__(self, service, engine=None, tray=None):
        self.service = service
        self.engine = engine
        self.tray = tray
        self.shown = False
        self.engine_started = 0
        self.actions = []
        self.quit_requested = FakeSignal()
        FakeWindow.created.append(self)

    def show(self):
        self.shown = True

    def show_and_raise(self):
        self.shown = True

    def start_engine(self):
        self.engine_started += 1

    def run_service_action(self, label, fn):
        self.actions.append((label, fn))


class FakePool:
    """Stands in for QThreadPool; records waitForDone timeouts."""

    waits: list = []

    @classmethod
    def globalInstance(cls):
        return cls()

    def waitForDone(self, msecs):
        FakePool.waits.append(msecs)
        return True


class FakeInstance:
    """Stands in for SingleInstance; ``running`` says whether another one answers."""

    running = False
    created: list = []

    def __init__(self):
        self.show_requested = FakeSignal()
        self.closed = False
        FakeInstance.created.append(self)

    def notify_or_listen(self):
        return FakeInstance.running

    def close(self):
        self.closed = True


class FakeTray:
    """Stands in for TrayController."""

    available = True

    def __init__(self, settings):
        self.settings = settings
        self.available = FakeTray.available
        self.quit_requested = FakeSignal()
        self.hidden = False

    def hide(self):
        self.hidden = True


class FakeEngine:
    """Stands in for MacroEngineService."""

    created: list = []

    def __init__(self):
        self.stops = 0
        FakeEngine.created.append(self)

    def stop(self):
        self.stops += 1


def install(monkeypatch, app_module, *, tray_available=True, running=False):
    """Patch every collaborator of ``app_module.main`` with the fakes above."""
    for cls in (FakeApp, FakeWindow, FakeInstance, FakeEngine):
        monkeypatch.setattr(cls, "created", [])
    monkeypatch.setattr(FakePool, "waits", [])
    monkeypatch.setattr(FakeTray, "available", tray_available)
    monkeypatch.setattr(FakeInstance, "running", running)
    monkeypatch.setattr(app_module, "QApplication", FakeApp)
    monkeypatch.setattr(app_module, "MainWindow", FakeWindow)
    monkeypatch.setattr(app_module, "QThreadPool", FakePool)
    monkeypatch.setattr(app_module, "SingleInstance", FakeInstance)
    monkeypatch.setattr(app_module, "TrayController", FakeTray)
    monkeypatch.setattr(app_module, "Settings", lambda: "settings")
    monkeypatch.setattr(app_module, "MacroEngineService", FakeEngine)
    themed = []
    monkeypatch.setattr(app_module, "apply_theme", themed.append)
    return themed
