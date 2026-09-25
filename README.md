# RazerUI

RazerUI is a standalone PyQt6 front end for [OpenRazer](https://openrazer.github.io/),
the open-source driver and daemon for Razer peripherals on Linux. It talks to the
OpenRazer daemon through the official `openrazer.client` Python library.

RazerUI does **not** depend on Polychromatic or RazerGenie.

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
python -m razerui
# or, once installed:
razerui
```

## Usage

- **Device list** (left, <kbd>Alt</kbd>+<kbd>C</kbd>): every device reported by the
  daemon, shown as "name (type)"; hover an entry to see its serial number.
- **Tabs** (right) for the selected device:
  - **Info** – name, type, serial, firmware and driver version.
  - **Lighting** – pick a zone and an effect, set colours/speed/direction, apply,
    and adjust brightness where supported.
  - **Mouse** – DPI (X/Y, optionally locked) and polling rate; only present for mice.
  - **Daemon** – daemon/client versions, repoll, restart, stop and start, plus the
    "sync effects" and "turn off on screensaver" settings.
- **Toolbar**: *Repoll* (<kbd>F5</kbd>) reconnects and re-reads the device list;
  *Restart daemon* (<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>R</kbd>) restarts the
  daemon and reconnects. The selected device is kept across repolls and restarts.
- The **status bar** shows results and errors of every action.

### Daemon restart

*Restart daemon* uses the systemd user unit when it is active: if
`systemctl --user is-active openrazer-daemon` succeeds, RazerUI runs
`systemctl --user restart openrazer-daemon`. Otherwise it falls back to
`openrazer-daemon -s` (stop), `killall openrazer-daemon` (in case it is still
running) and then starts `openrazer-daemon` again, before reconnecting.

### Without the daemon or python3-openrazer

If `python3-openrazer` is not installed, the daemon is not running, or no devices
are found, RazerUI does not crash: it shows an empty state with the error message
and *Start daemon* / *Retry* buttons.

## Development and tests

```sh
pip install -e .[dev]
python -m pytest
```

The test suite uses a fake `openrazer` package (see `tests/conftest.py`), so it
runs without the daemon or real hardware.
