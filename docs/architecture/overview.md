<!-- generated:start cap:overview-intro -->
# Architecture Overview

5 component(s) declared on the architecture canvas. Topology: [system-map.md](system-map.md).
<!-- generated:end cap:overview-intro -->








<!-- generated:start comp:openrazer-daemon -->
## OpenRazer Daemon (`openrazer-daemon`, CUSTOM)

External, independently-packaged system daemon (OpenRazer project) that owns direct USB/HID communication with Razer hardware and exposes it over D-Bus (org.razer). Both RazerGenie and Polychromatic are alternative GUI front-ends to this same daemon; its source is not part of this repository.

**Tech:** D-Bus (org.razer), Python daemon (external project)
<!-- generated:end comp:openrazer-daemon -->

<!-- generated:start comp:razerui -->
## RazerUI (`razerui`, FRONTEND)
<!-- generated:end comp:razerui -->

<!-- generated:start comp:macro-engine -->
## Macro Engine (`macro-engine`, BACKEND)
<!-- generated:end comp:macro-engine -->

<!-- generated:start comp:sysmon-overlay -->
## Sysmon Overlay (Waybar + collector) (`sysmon-overlay`, BACKEND)

System monitor overlay: an external `waybar` child process (own session/process group, pid in $XDG_RUNTIME_DIR/hueberry/sysmon.pid) spawned and managed by RazerUI's SysmonController (hueberry/sysmon/controller.py). hueberry/sysmon/waybar.py writes its config under $XDG_CONFIG_HOME/hueberry/sysmon with a `custom/sysmon` module that runs `python -m hueberry.sysmon.collector --config PATH`; the collector reads /proc and /sys and prints one JSON metrics line per interval for Waybar to draw.

**Tech:** Waybar (external binary), Python (hueberry.sysmon.collector), Linux /proc and /sys
<!-- generated:end comp:sysmon-overlay -->

<!-- generated:start comp:sysmon -->
## Sysmon (`sysmon`, CUSTOM)
<!-- generated:end comp:sysmon -->
