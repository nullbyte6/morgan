#  Copyright (c) 2026 Diego.
#
#  SPDX-License-Identifier: GPL-3.0-or-later
#
#  This file is part of arlo.
#
#  This program is free software: you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation, either version 3
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty
#  of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#  See the GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program. If not, see <https://www.gnu.org/licenses/>.
"""Minimize application windows through the active platform."""

import json

from src.platforms import current_platform


def minimize_all_windows(except_applications: list[str] | None = None) -> str:
    """Minimize taskbar windows, optionally keeping named apps visible."""
    exclusions = [
        value.strip().casefold() for value in (except_applications or [])
        if value.strip()
    ]
    context = {"except_applications": except_applications or []}
    try:
        platform = current_platform()
        minimized = []
        kept = []
        failures = []
        for window in platform.list_windows():
            identity = " ".join((
                window.get("title") or "",
                window.get("executable") or "",
            )).casefold()
            if any(exclusion in identity for exclusion in exclusions):
                kept.append(window.get("title") or window.get("executable"))
                continue
            if window["minimized"]:
                continue
            if platform.minimize_window(window["hwnd"]):
                minimized.append(window.get("title") or window.get("executable"))
            else:
                failures.append(window.get("title") or window.get("executable"))
        return json.dumps({
            **context,
            "status": "completed" if not failures else "partial",
            "minimized": minimized,
            "kept": kept,
            "failures": failures,
        }, ensure_ascii=False)
    except (OSError, ValueError) as error:
        return json.dumps({
            **context,
            "status": "error",
            "error": str(error),
        }, ensure_ascii=False)
