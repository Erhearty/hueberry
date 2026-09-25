# Hueberry

Hueberry is a standalone PyQt6 front end for [OpenRazer](https://openrazer.github.io/),
the open-source driver and daemon for Razer peripherals on Linux. It talks to the
OpenRazer daemon through the official `openrazer.client` Python library.

Hueberry does **not** depend on Polychromatic or RazerGenie.

Licensed under the GNU General Public License v3.0 or later (`GPL-3.0-or-later`),
see [LICENSE](LICENSE).

## Requirements

- Python 3.10+
- PyQt6 (>= 6.4)
- The OpenRazer daemon and its Python client library, installed **from your distro**
  (they are not installable from PyPI):

  ```sh
  # Debian / Ubuntu (with the OpenRazer repository/PPA)
  sudo apt install openrazer-meta
  # Fedora (with the OpenRazer repository)
  sudo dnf install openrazer-meta
  ```

  This provides `openrazer-daemon` and `python3-openrazer`. Remember to add your
  user to the `plugdev` group and log out/in as described in the OpenRazer docs.

## Virtual environments

Because `openrazer` lives in the system site-packages (installed by the distro
package), a virtual environment must be created with access to them, otherwise
`import openrazer` fails inside the venv:

```sh
python3 -m venv --system-site-packages .venv
. .venv/bin/activate
```

## Running

```sh
python -m hueberry
# or, once installed:
hueberry
```

## Usage

- **Home screen**: a grid of device cards, one per device reported by the daemon,
  each showing an icon, the device name and its type; hover a card to see its
  serial number. Move between cards with <kbd>Tab</kbd> / arrow keys and open one
  with <kbd>Enter</kbd> or <kbd>Space</kbd> (or a click).
- **Device page** for the opened device, with a header (icon and name) and tabs:
  - **Lighting** – pick a zone and an effect, set colours/speed/direction, apply,
    and adjust brightness where supported. The **Erheart** preset animates a
    pink/purple diagonal wave, drawn by Hueberry itself: devices with a key
    matrix get a per-key wave, other devices one animated colour, all in sync.
    It runs only while Hueberry is open and stops when another effect is applied
    to that device, when the device disappears, or when the app quits.
  - **Performance** – DPI (X/Y, optionally locked) and polling rate; only present
    for mice.
  - **Info** – name, type, serial, firmware and driver version.

  *← Devices* (<kbd>Alt</kbd>+<kbd>Left</kbd> or <kbd>Esc</kbd>) returns to the home screen.
- **Daemon status bar** (bottom): a coloured dot and the daemon state, plus
  - *Restart* – restarts the daemon and reconnects
    (also <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>R</kbd>);
  - *Re-scan* – reconnects and re-reads the device list (also <kbd>F5</kbd>);
  - *Daemon…* – opens a window with daemon/client versions, stop and start, plus
    the "sync effects" and "turn off on screensaver" settings.

  The opened device is kept across re-scans and restarts; the status bar also
  shows results and errors of every action.
- The app uses a dark theme with a single accent colour; device icons are
  original, generic glyphs drawn by the app.

### Daemon restart

*Restart daemon* uses the systemd user unit when it is active: if
`systemctl --user is-active openrazer-daemon` succeeds, Hueberry runs
`systemctl --user restart openrazer-daemon`. Otherwise it falls back to
`openrazer-daemon -s` (stop), `killall openrazer-daemon` (in case it is still
running) and then starts `openrazer-daemon` again, before reconnecting.

### Without the daemon or python3-openrazer

If `python3-openrazer` is not installed, the daemon is not running, or no devices
are found, Hueberry does not crash: it shows an empty state with the error message
and *Start daemon* / *Retry* buttons.

## Development and tests

```sh
pip install -e .[dev]
python -m pytest
```

The test suite uses a fake `openrazer` package (see `tests/conftest.py`), so it
runs without the daemon or real hardware.
