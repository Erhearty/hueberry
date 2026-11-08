# Installing Hueberry

This guide takes you from a bare Linux desktop to a running Hueberry, with
the OpenRazer daemon, optional macro support, a launcher entry and autostart.

Hueberry is a Python package (PyQt6 front end) installed with
[pipx](https://pipx.pypa.io/). The OpenRazer daemon and its Python client
(`openrazer`) are **not** on PyPI, so they come from your distro.

## 1. Distro packages

### OpenRazer

| Distro           | Packages                                        | Notes                                              |
|------------------|-------------------------------------------------|----------------------------------------------------|
| Debian / Ubuntu  | `openrazer-meta`                                | Needs the OpenRazer repository or PPA.             |
| Fedora           | `openrazer-meta`                                | Needs the OpenRazer repository.                    |
| Arch             | `openrazer-daemon`, `python-openrazer`          | Packages from the AUR; no extra repository needed. |

```sh
# Debian / Ubuntu (with the OpenRazer repository/PPA added)
sudo apt install openrazer-meta
# Fedora (with the OpenRazer repository added)
sudo dnf install openrazer-meta
# Arch (AUR, e.g. with your AUR helper)
yay -S openrazer-daemon python-openrazer
```

`openrazer-meta` provides `openrazer-daemon` and `python3-openrazer`. Add
yourself to the `plugdev` group, then log out and back in, as described in the
[OpenRazer documentation](https://openrazer.github.io/):

```sh
sudo usermod -aG plugdev "$USER"
```

### evdev (macros only)

The macro engine needs python-evdev. Skip this if you do not use macros.

```sh
# Debian / Ubuntu
sudo apt install python3-evdev
# Fedora
sudo dnf install python3-evdev
# Arch
sudo pacman -S python-evdev
```

You can instead let pipx fetch it from PyPI (see step 2, `hueberry[macros]`).

### Qt SVG module

Device graphics need Qt's SVG module. Some distros ship it separately, e.g.
`python3-pyqt6.qtsvg` on Debian/Ubuntu. If the LED preview shows only a plain
grid for supported devices, install it.

### waybar (optional)

The *Sysmon* overlay needs `waybar`. Without it the *Sysmon* page reports
"waybar not found".

```sh
sudo apt install waybar     # Debian / Ubuntu
sudo dnf install waybar     # Fedora
sudo pacman -S waybar       # Arch
```

## 2. Install Hueberry with pipx

Hueberry is not published on PyPI, so pipx installs it straight from the
GitHub repository:

```sh
sudo apt install pipx       # Debian / Ubuntu; use dnf / pacman on other distros
pipx ensurepath
pipx install --system-site-packages \
    "hueberry[macros] @ git+https://github.com/Erhearty/hueberry.git"
```

Leave out `[macros]` if you do not use macros; when the distro's
python3-evdev is installed (step 1), it is used and nothing is fetched from
PyPI. From a source checkout, `pipx install --system-site-packages ".[macros]"`
does the same.

The `hueberry` command is placed in `~/.local/bin`. Open a new shell if it is
not found.

`--system-site-packages` is required: pipx otherwise creates an isolated
environment that cannot see the distro's `openrazer` module. To check the
distro module itself works:

```sh
python3 -c "import openrazer.client; print('ok')"
```

To update later, run `pipx reinstall hueberry` (or `pipx install --force ...`
with the command above).

### Running from a source checkout

```sh
git clone https://github.com/Erhearty/hueberry.git hueberry && cd hueberry
python3 -m venv --system-site-packages .venv
. .venv/bin/activate
pip install -e .[macros]
python -m hueberry
```

The `--system-site-packages` flag is required so the venv can import `openrazer`.

## 3. OpenRazer daemon

Hueberry talks to `openrazer-daemon`. Start it as a systemd user service:

```sh
systemctl --user enable --now openrazer-daemon
systemctl --user is-active openrazer-daemon   # should print "active"
```

Hueberry's *Restart* button uses this user unit when it is active. Without the
unit, Hueberry falls back to starting `openrazer-daemon` directly.

Plug in your device and open Hueberry; the device should appear on the home
screen. Use *Re-scan* in the header bar after plugging in a device while
Hueberry is already open.

## 4. udev and uinput rule (macros)

Macros need access to `/dev/uinput` (to create the virtual device) and to
`/dev/input/event*` (to grab the physical device). The repository ships
`data/udev/70-hueberry-uinput.rules`, which makes `/dev/uinput` owned by the
`input` group with mode `0660`. Reading `/dev/input/event*` is already granted
to the `input` group by the default udev rules of most distros.

From a source checkout, run:

```sh
sudo install -m 0644 data/udev/70-hueberry-uinput.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
sudo usermod -aG input "$USER"   # then log out and back in
```

Log out and back in so the new group membership takes effect.

> **Security caveat:** every program run by a member of the `input` group can
> read every keystroke (including passwords) and inject arbitrary input. Only
> do this on a machine where you accept that. To undo it, remove the rule file,
> reload udev, and run `sudo gpasswd -d "$USER" input`.

The rule file is not installed by pipx. If you installed Hueberry with pipx
and have no checkout, clone the repository
(`git clone https://github.com/Erhearty/hueberry.git`) or download
`data/udev/70-hueberry-uinput.rules` from it first.

## 5. Launcher entry

The repository ships a desktop entry and an icon:

- `data/applications/hueberry.desktop` - starts `hueberry` (`Exec=hueberry`)
- `data/icons/hueberry.svg` - the application icon (`Icon=hueberry`)

Hueberry sets no window icon of its own, so the launcher icon comes only from
the installed SVG. Install both from a source checkout (or a downloaded copy of
the repository) for the current user:

```sh
install -Dm0644 data/applications/hueberry.desktop \
    ~/.local/share/applications/hueberry.desktop
install -Dm0644 data/icons/hueberry.svg \
    ~/.local/share/icons/hicolor/scalable/apps/hueberry.svg
update-desktop-database ~/.local/share/applications 2>/dev/null
gtk-update-icon-cache -q ~/.local/share/icons/hicolor 2>/dev/null
```

For all users, install to `/usr/share/applications/` and
`/usr/share/icons/hicolor/scalable/apps/` with `sudo` instead.

The `Exec=hueberry` line needs `hueberry` on your `PATH`, which is true for a
pipx install once `~/.local/bin` is on `PATH`.

## 6. Tray and autostart

Hueberry keeps running in the system tray when its window is closed. Macros
work only while Hueberry is running, so closing the window does not stop them.
*Quit* in the tray menu stops Hueberry and all macros. The setting
*Keep running in the background when closed* turns the tray behaviour off, so
closing the window quits.

### Start Hueberry at login

The tray menu entry is labelled exactly:

```
Start Hueberry at login
```

Ticking it writes `~/.config/autostart/hueberry.desktop`
(or `$XDG_CONFIG_HOME/autostart/hueberry.desktop`). The file contains:

- `Exec=` the full path of the `hueberry` script (or `python -m hueberry` if the
  script is not on `PATH`), followed by `--background`, so Hueberry starts with
  the tray icon only and no window;
- the marker line `X-Hueberry-Autostart=true`.

Unticking the entry removes the file. Hueberry only ever creates, overwrites
or deletes a `hueberry.desktop` that carries this marker; if a file with the
same name was written by something else, Hueberry refuses to touch it and
reports an error. Remove that file by hand if you want autostart managed by
Hueberry.

To check the setup, log out and back in, or inspect the file:

```sh
cat ~/.config/autostart/hueberry.desktop
```

### Tray icon on GNOME

GNOME does not show tray icons by default. Install the
*AppIndicator and KStatusNotifierItem Support* extension (for example from your
distro or extensions.gnome.org) and enable it.

## 7. Troubleshooting

**`import openrazer` fails, or Hueberry reports that openrazer is missing.**
The pipx environment cannot see the distro module. Reinstall with
`pipx install --force --system-site-packages` and the source from step 2. In a venv, create
it with `python3 -m venv --system-site-packages .venv`.

**The daemon status shows an error, or no devices are found.**
Check the daemon with `systemctl --user status openrazer-daemon`, and start it
with `systemctl --user enable --now openrazer-daemon`. Confirm you are in the
`plugdev` group (`id -nG`) and have logged out and back in since adding it. In
Hueberry, the empty state offers *Start daemon* and *Retry*.

**The *Sysmon* page reports "waybar not found".**
Install `waybar` (step 1).

**Macros do not work, or a device shows as busy.**
- `Permission denied` on `/dev/uinput`: the udev rule is not active. Run
  `ls -l /dev/uinput`; the group should be `input` and the mode `crw-rw----`.
  Re-check step 4, and confirm `id -nG` lists `input` after logging back in.
- *busy*: another program holds the device, most often OpenRazer's own M-key
  macro mode. Turn that mode off there, then reload in Hueberry.
- The engine is not started: it runs only while Hueberry is running.

**The launcher entry does not appear or has no icon.**
Re-run the `install` commands in step 5, then log out and back in, or run
`update-desktop-database ~/.local/share/applications`. Check the icon is
installed at `~/.local/share/icons/hicolor/scalable/apps/hueberry.svg`.

**Hueberry does not start at login.**
Check `~/.config/autostart/hueberry.desktop` exists and that its `Exec=` line
points to a working `hueberry` command. On GNOME, make sure the AppIndicator
extension is enabled, or the tray icon will not show.

**Two System monitor overlays appear.**
A hand-run Waybar sysmon setup under `~/.config/waybar` is still running. Stop
that Waybar instance; Hueberry never modifies `~/.config/waybar`.

**The app shows a corrupted macro list.**
An unreadable `~/.config/hueberry/macros.json` is moved aside to
`macros.json.bak`. Restore the backup by hand if needed.

For anything else, the status bar at the bottom of the Hueberry window shows the
result and error of each action.
