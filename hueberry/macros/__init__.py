# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Macro data model, storage and the IPC protocol shared by GUI and engine.

Nothing here imports Qt or ``evdev`` at module level: the GUI must be able to
edit macros without python-evdev, and the engine must stay Qt-free.
"""
