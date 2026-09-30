<!-- generated:start file:system-map -->
# System Map

```mermaid
graph TD
    macro-engine["Macro Engine <br/> <small>(BACKEND)</small>"]
    openrazer-daemon["OpenRazer Daemon <br/> <small>(CUSTOM)</small>"]
    razerui["RazerUI <br/> <small>(FRONTEND)</small>"]
    sysmon["Sysmon <br/> <small>(CUSTOM)</small>"]
    sysmon-overlay["Sysmon Overlay (Waybar + collector) <br/> <small>(BACKEND)</small>"]
    macro-engine -->|Unix domain socket ($XDG_RUNTIME_DIR/hueberry/gui.sock, GUI single-instance socket; newline-terminated allow-listed action names, e.g. toggle-sysmon)| razerui
    razerui -->|Unix domain socket IPC (child process spawned via subprocess)| macro-engine
    razerui -->|D-Bus (via system openrazer.client Python library); lifecycle control via subprocess (systemctl --user is-active/restart openrazer-daemon, else openrazer-daemon -s / killall / openrazer-daemon)| openrazer-daemon
    razerui -->|Subprocess (spawns/stops waybar child in its own process group; pid file $XDG_RUNTIME_DIR/hueberry/sysmon.pid; writes Waybar config + sysmon.json)| sysmon-overlay
```

## Components

- [Macro Engine](overview.md) (`macro-engine`, backend)
- [OpenRazer Daemon](overview.md) (`openrazer-daemon`, custom)
- [RazerUI](overview.md) (`razerui`, frontend)
- [Sysmon](overview.md) (`sysmon`, custom)
- [Sysmon Overlay (Waybar + collector)](overview.md) (`sysmon-overlay`, backend)

## Interactions

- [macro-engine → razerui](interactions/macro-engine--razerui.md) via `Unix domain socket ($XDG_RUNTIME_DIR/hueberry/gui.sock, GUI single-instance socket; newline-terminated allow-listed action names, e.g. toggle-sysmon)`
- [razerui → macro-engine](interactions/razerui--macro-engine.md) via `Unix domain socket IPC (child process spawned via subprocess)`
- [razerui → openrazer-daemon](interactions/razerui--openrazer-daemon.md) via `D-Bus (via system openrazer.client Python library); lifecycle control via subprocess (systemctl --user is-active/restart openrazer-daemon, else openrazer-daemon -s / killall / openrazer-daemon)`
- [razerui → sysmon-overlay](interactions/razerui--sysmon-overlay.md) via `Subprocess (spawns/stops waybar child in its own process group; pid file $XDG_RUNTIME_DIR/hueberry/sysmon.pid; writes Waybar config + sysmon.json)`
<!-- generated:end file:system-map -->
