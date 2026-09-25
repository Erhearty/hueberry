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
- **RazerUI** (`razerui`) - frontend component.
<!-- generated:end comp:razerui -->
