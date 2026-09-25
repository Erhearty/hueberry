# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 RazerUI contributors
"""Backend layer: OpenRazer daemon control and device introspection.

Nothing here imports ``openrazer`` at module level; the client library is
loaded lazily so RazerUI can start (and report the problem) without it.
"""
