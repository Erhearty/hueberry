<!-- generated:start cap:overview-intro -->
# Architecture Overview

2 component(s) declared on the architecture canvas. Topology: [system-map.md](system-map.md).
<!-- generated:end cap:overview-intro -->








<!-- generated:start comp:openrazer-daemon -->
## OpenRazer Daemon (`openrazer-daemon`, CUSTOM)

External, independently-packaged system daemon (OpenRazer project) that owns direct USB/HID communication with Razer hardware and exposes it over D-Bus (org.razer). Both RazerGenie and Polychromatic are alternative GUI front-ends to this same daemon; its source is not part of this repository.

**Tech:** D-Bus (org.razer), Python daemon (external project)
<!-- generated:end comp:openrazer-daemon -->

<!-- generated:start comp:razerui -->
## RazerUI (`razerui`, FRONTEND)
<!-- generated:end comp:razerui -->
