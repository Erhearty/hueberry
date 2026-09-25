<!-- generated:start file:system-map -->
# System Map

```mermaid
graph TD
    openrazer-daemon["OpenRazer Daemon <br/> <small>(CUSTOM)</small>"]
    razerui["RazerUI <br/> <small>(FRONTEND)</small>"]
    razerui -->|D-Bus (via system openrazer.client Python library)| openrazer-daemon
```

## Components

- [OpenRazer Daemon](overview.md) (`openrazer-daemon`, custom)
- [RazerUI](overview.md) (`razerui`, frontend)

## Interactions

- [razerui → openrazer-daemon](interactions/razerui--openrazer-daemon.md) via `D-Bus (via system openrazer.client Python library)`
<!-- generated:end file:system-map -->
