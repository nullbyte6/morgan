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
"""The workspace button row: Nova's star, from which the other workspace buttons slide out."""
from PySide6.QtCore import QEasingCurve, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from src.init.lang import tr

STAR = "\U000f0ae2"
BUTTON_SIZE = 48
BUTTON_GAP = 8
SLIDE_MS = 220


class WorkspaceNavigation(QWidget):
    """Press the Nova star to unfold the workspace buttons; Ctrl+click opens Nova itself."""

    nova_requested = Signal(object)

    def __init__(self, buttons: list[QPushButton], parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("novaNavigation")
        self._buttons = buttons
        self._expanded = False
        self._full = len(buttons) * BUTTON_SIZE + max(0, len(buttons) - 1) * BUTTON_GAP

        self.nova = QPushButton(STAR)
        self.nova.setObjectName("novaNav")
        self.nova.setProperty("expanded", False)
        self.nova.setFixedSize(BUTTON_SIZE, BUTTON_SIZE)
        self.nova.setCursor(Qt.CursorShape.PointingHandCursor)
        self.nova.clicked.connect(self._pressed)

        self.tray = QWidget(self)
        self.tray.setObjectName("novaTray")
        self.tray.setFixedHeight(BUTTON_SIZE)
        for button in buttons:
            button.setParent(self.tray)
            button.show()
        self._place(0)
        self.tray.setFixedWidth(0)
        self.tray.hide()

        self._slide = QVariantAnimation(self)
        self._slide.setDuration(SLIDE_MS)
        self._slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._slide.valueChanged.connect(lambda width: self._place(int(width)))
        self._slide.finished.connect(self._settled)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(BUTTON_GAP)
        layout.addWidget(self.nova)
        layout.addWidget(self.tray)
        self.refresh_language()

    @property
    def expanded(self) -> bool:
        return self._expanded

    def _pressed(self) -> None:
        if QGuiApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier:
            self.nova_requested.emit(self.nova)
        else:
            self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        if expanded == self._expanded:
            return
        self._expanded = expanded
        self.nova.setProperty("expanded", expanded)
        self.nova.style().unpolish(self.nova)
        self.nova.style().polish(self.nova)
        self._slide.stop()
        if expanded:
            self.tray.show()
        self._slide.setStartValue(self.tray.width())
        self._slide.setEndValue(self._full if expanded else 0)
        self._slide.start()

    def _place(self, width: int) -> None:
        """Slide the buttons out from behind the star while the tray grows to width."""
        self.tray.setFixedWidth(width)
        for index, button in enumerate(self._buttons):
            button.move(index * (BUTTON_SIZE + BUTTON_GAP) - (self._full - width), 0)

    def _settled(self) -> None:
        if not self._expanded:
            self.tray.hide()

    def refresh_language(self) -> None:
        self.nova.setToolTip(tr("nova.nav.tooltip"))
