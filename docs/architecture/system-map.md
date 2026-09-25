<!-- generated:start file:system-map -->
# System Map

```mermaid
graph TD
    macro-engine["Macro Engine <br/> <small>(BACKEND)</small>"]
    openrazer-daemon["OpenRazer Daemon <br/> <small>(CUSTOM)</small>"]
    razerui["RazerUI <br/> <small>(FRONTEND)</small>"]
    razerui -->|Unix domain socket IPC (child process spawned via subprocess)| macro-engine
    razerui -->|D-Bus (via system openrazer.client Python library); lifecycle control via subprocess (systemctl --user is-active/restart openrazer-daemon, else openrazer-daemon -s / killall / openrazer-daemon)| openrazer-daemon
```

## Components

- [Macro Engine](overview.md) (`macro-engine`, backend)
- [OpenRazer Daemon](overview.md) (`openrazer-daemon`, custom)
- [RazerUI](overview.md) (`razerui`, frontend)

## Interactions

- [razerui → macro-engine](interactions/razerui--macro-engine.md) via `Unix domain socket IPC (child process spawned via subprocess)`
- [razerui → openrazer-daemon](interactions/razerui--openrazer-daemon.md) via `D-Bus (via system openrazer.client Python library); lifecycle control via subprocess (systemctl --user is-active/restart openrazer-daemon, else openrazer-daemon -s / killall / openrazer-daemon)`
<!-- generated:end file:system-map -->
