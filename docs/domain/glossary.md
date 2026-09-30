<!-- generated:start cap:glossary-intro -->
# System Intent & Glossary

The overall outcome this system exists to achieve, the canonical component names projected from the architecture canvas, and the authoritative business vocabulary. Treat these terms as carrying their defined meaning throughout the project.
<!-- generated:end cap:glossary-intro -->

<!-- generated:start cap:components-heading -->
## Components

Canonical component names projected from the architecture canvas.
<!-- generated:end cap:components-heading -->








<!-- generated:start comp:openrazer-daemon -->
- **OpenRazer Daemon** (`openrazer-daemon`) - custom component. External, independently-packaged system daemon (OpenRazer project) that owns direct USB/HID communication with Razer hardware and exposes it over D-Bus (org.razer). Both RazerGenie and Polychromatic are alternative GUI front-ends to this same daemon; its source is not part of this repository.
<!-- generated:end comp:openrazer-daemon -->

<!-- generated:start comp:razerui -->
- **RazerUI** (`razerui`) - frontend component. PyQt6 front end (package hueberry) for OpenRazer: device pages, whole-device lighting presets, per-key advanced effects (key groups with static/wave/breathing/spectrum/reactive/ripple/starlight, rendered by a background runtime that keeps running in the tray), named advanced presets with last-used restore, macros and sysmon.
<!-- generated:end comp:razerui -->

<!-- generated:start comp:macro-engine -->
- **Macro Engine** (`macro-engine`) - backend component.
<!-- generated:end comp:macro-engine -->

<!-- generated:start cap:system-intent -->
## System Intent

UI for openrazer. Main goals are:
- LED presets
- independent OR combined LED setup
- visual preview for the LED setup, including LED position and color of each connected device
- Generate advanced effects from presets(per-key effect, effect rotation, speed controll)
- Macro recording and editing
- Macro assignement to any key
<!-- generated:end cap:system-intent -->

<!-- generated:start comp:sysmon-overlay -->
- **Sysmon Overlay (Waybar + collector)** (`sysmon-overlay`) - backend component. System monitor overlay: an external `waybar` child process (own session/process group, pid in $XDG_RUNTIME_DIR/hueberry/sysmon.pid) spawned and managed by RazerUI's SysmonController (hueberry/sysmon/controller.py). hueberry/sysmon/waybar.py writes its config under $XDG_CONFIG_HOME/hueberry/sysmon with a `custom/sysmon` module that runs `python -m hueberry.sysmon.collector --config PATH`; the collector reads /proc and /sys and prints one JSON metrics line per interval for Waybar to draw.
<!-- generated:end comp:sysmon-overlay -->

<!-- generated:start comp:sysmon -->
- **Sysmon** (`sysmon`) - custom component.
<!-- generated:end comp:sysmon -->
