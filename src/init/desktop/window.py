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
"""Frameless desktop window fitted to the current screen's work area."""

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QMainWindow


class DesktopWindow(QMainWindow):
    """Keep the outer surface transparent and follow OS work-area changes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("arloWindow")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._screen_tracking_started = False

        app = QApplication.instance()
        for screen in app.screens():
            self._watch_screen(screen)
        app.screenAdded.connect(self._watch_screen)

    def _watch_screen(self, screen):
        screen.availableGeometryChanged.connect(self.fit_available_screen)
        screen.geometryChanged.connect(self.fit_available_screen)

    def fit_available_screen(self, *_):
        """Use Qt's logical coordinates, excluding OS-reserved taskbar space."""
        if not self.isVisible() or self.isMinimized():
            return
        screen = self.screen()
        if screen is not None:
            available = screen.availableGeometry()
            if self.geometry() != available:
                self.setGeometry(available)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._screen_tracking_started:
            self.windowHandle().screenChanged.connect(self.fit_available_screen)
            self._screen_tracking_started = True
        self.fit_available_screen()
        QTimer.singleShot(0, self.fit_available_screen)
