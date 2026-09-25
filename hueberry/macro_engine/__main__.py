# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""Entry point for ``python -m hueberry.macro_engine --parent-pid <pid>``."""

from hueberry.macro_engine.main import main

raise SystemExit(main())
