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
    and adjust brightness where supported.
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

## Macros

Hueberry can bind a macro to any key or button of any input device, including
on Wayland. A small helper process, the *macro engine*
(`python -m hueberry.macro_engine`, started by Hueberry itself, never by hand),
grabs a device that has enabled macros, re-emits all its other events through a
virtual device (named `hueberry-virtual:<device name>`) and plays a macro when
its trigger is pressed. Macros are stored in `~/.config/hueberry/macros.json`
(or `$XDG_CONFIG_HOME/hueberry/macros.json`); an unreadable file is moved aside
to `macros.json.bak`.

### Requirements

- python-evdev, either from your distro or via the `macros` extra:

  ```sh
  # Debian / Ubuntu
  sudo apt install python3-evdev
  # Fedora
  sudo dnf install python3-evdev
  # or, in a venv
  pip install -e .[macros]
  ```

- Access to `/dev/uinput` and to `/dev/input/event*`. Install the shipped udev
  rule and join the `input` group, then log out and back in:

  ```sh
  sudo install -m 0644 data/udev/70-hueberry-uinput.rules /etc/udev/rules.d/
  sudo udevadm control --reload-rules && sudo udevadm trigger
  sudo usermod -aG input "$USER"
  ```

  **Security caveat:** every program you run as a member of the `input` group
  can read all keystrokes (including passwords) and inject arbitrary input.
  Only do this on a machine where you accept that.

### When macros are active

- Macros work only while Hueberry is running – with its window open *or*
  minimised to the system tray. Closing the window keeps Hueberry in the tray;
  *Quit* from the tray menu stops it, and with it all macros. The
  *Keep running in the background when closed* setting turns this off, so
  closing the window quits.
- The tray menu entry *Start Hueberry at login* writes
  `~/.config/autostart/hueberry.desktop`, which starts Hueberry with
  `--background` (tray only, no window).
- On GNOME the tray icon needs the *AppIndicator and KStatusNotifierItem
  Support* extension.
- The engine exits together with Hueberry: if Hueberry quits or crashes, every
  grabbed device is released immediately and works normally again.

### Conflicts and limitations

- OpenRazer's own M-key / macro mode (and any other tool that grabs input
  devices) conflicts with Hueberry's macros. If another program already holds
  the device, Hueberry shows it as **busy** and leaves it alone; turn off the
  other tool's macro mode and reload.
- Macro steps are key/button presses, releases, taps and delays only. Running
  shell commands is intentionally unsupported, and a `macros.json` containing
  such steps is rejected.

## Development and tests

```sh
pip install -e .[dev]
python -m pytest
```

The test suite uses fake `openrazer` and `evdev` packages (see `tests/conftest.py`
and `tests/fake_evdev.py`), so it runs without the daemon, python-evdev or real
hardware.
