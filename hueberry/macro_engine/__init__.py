# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""The macro engine: a Qt-free child process of Hueberry.

It grabs input devices that have macros (evdev), forwards everything else
through a uinput clone and plays macros on trigger presses. ``evdev`` is only
imported lazily, so this package imports (and reports the problem) without it.
Run it as ``python -m hueberry.macro_engine --parent-pid <pid>``.
"""
