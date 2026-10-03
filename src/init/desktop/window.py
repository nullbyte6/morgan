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
"""Framed desktop window whose title bar follows the active theme."""

import ctypes
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow

from src.init.theme import current_theme

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36


def _colorref(color) -> ctypes.c_uint:
    return ctypes.c_uint(color.red() | color.green() << 8 | color.blue() << 16)


class DesktopWindow(QMainWindow):
    """Resizable window with a native frame colored from the theme."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("assistantWindow")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setWindowState(Qt.WindowMaximized)

    def apply_frame_theme(self, theme):
        """Match the native title bar and border to the theme's surface colors."""
        if sys.platform != "win32":
            return
        background = theme.color("surface_sunken")
        dark = background.lightness() < 128
        attributes = (
            (DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.c_int(int(dark))),
            (DWMWA_CAPTION_COLOR, _colorref(background)),
            (DWMWA_BORDER_COLOR, _colorref(theme.color("border"))),
            (DWMWA_TEXT_COLOR, _colorref(theme.color("text"))),
        )
        hwnd = int(self.winId())
        for attribute, value in attributes:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value))

    def showEvent(self, event):
        super().showEvent(event)
        self.apply_frame_theme(current_theme())
