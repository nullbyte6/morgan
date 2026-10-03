#  Copyright (c) 2026 Diego.
#
#  SPDX-License-Identifier: GPL-3.0-or-later
#
#  This file is part of morgan.
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
"""Native window frames, taskbar identity and desktop launching on Windows."""

import ctypes
from ctypes import wintypes

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36


def _colorref(rgb):
    red, green, blue = rgb
    return ctypes.c_uint(red | green << 8 | blue << 16)


def style_window_frame(handle, dark, caption, border, text):
    attributes = (
        (DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.c_int(int(dark))),
        (DWMWA_CAPTION_COLOR, _colorref(caption)),
        (DWMWA_BORDER_COLOR, _colorref(border)),
        (DWMWA_TEXT_COLOR, _colorref(text)),
    )
    for attribute, value in attributes:
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            handle, attribute, ctypes.byref(value), ctypes.sizeof(value))


def window_height(handle):
    rect = wintypes.RECT()
    if ctypes.windll.user32.GetWindowRect(handle, ctypes.byref(rect)):
        return rect.bottom - rect.top
    return None


def set_app_id(app_id):
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)


def desktop_launcher(installation, root):
    if installation is not None:
        return installation / "Morgan.exe"
    return root / "scripts" / "morgan-start.bat"


def launch_command(launcher, root):
    if launcher.suffix.casefold() == ".exe":
        return [str(launcher)], launcher.parent
    return ["cmd.exe", "/c", str(launcher)], root
