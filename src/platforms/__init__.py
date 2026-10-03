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
"""Select the platform package that provides operating system services to the core."""

from functools import lru_cache
import sys

from .base import Platform, TelemetryError, UnsupportedOperation

__all__ = ["Platform", "TelemetryError", "UnsupportedOperation", "current_platform"]


@lru_cache(maxsize=1)
def current_platform() -> Platform:
    if sys.platform == "win32":
        from .winx64 import WinX64Platform
        return WinX64Platform()
    if sys.platform == "darwin":
        from .macx64 import MacX64Platform
        return MacX64Platform()
    return Platform()
