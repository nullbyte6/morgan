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
"""Framed desktop window whose title bar follows the active theme."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QMainWindow

from src.init.theme import current_theme
from src.platforms import current_platform


def _rgb(color) -> tuple[int, int, int]:
    return color.red(), color.green(), color.blue()


class DesktopWindow(QMainWindow):
    """Resizable window with a native frame colored from the theme."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("assistantWindow")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setAutoFillBackground(True)
        self._fill_background(current_theme())
        self.setWindowState(Qt.WindowMaximized)

    def _fill_background(self, theme):
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, theme.color("surface_sunken"))
        self.setPalette(palette)

    def apply_frame_theme(self, theme):
        """Match the native title bar and border to the theme's surface colors."""
        background = theme.color("surface_sunken")
        self._fill_background(theme)
        current_platform().style_window_frame(
            int(self.winId()), background.lightness() < 128, _rgb(background),
            _rgb(theme.color("border")), _rgb(theme.color("text")))

    def showEvent(self, event):
        super().showEvent(event)
        self.apply_frame_theme(current_theme())
