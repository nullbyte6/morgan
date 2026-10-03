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
"""Windows x64 services for Arlo, backed by Win32, the Shell and PowerShell."""

from ..base import Platform
from . import folders, notifications, windows


class WinX64Platform(Platform):
    name = "winx64"

    list_windows = staticmethod(windows.get_open_windows)
    launch_application = staticmethod(windows.launch_application)
    request_window_close = staticmethod(windows.request_window_close)
    minimize_window = staticmethod(windows.minimize_window)
    known_folder = staticmethod(folders.known_folder)
    local_drives = staticmethod(folders.local_drives)
    notify = staticmethod(notifications.notify)
    ask_notification = staticmethod(notifications.ask_notification)
