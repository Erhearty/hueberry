# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 RazerUI contributors
"""PyQt6 widgets for RazerUI.

Nothing in this package imports openrazer: all device and daemon access goes
through :mod:`razerui.backend`, and blocking calls run off the GUI thread via
:func:`razerui.ui.worker.run_async`.
"""
