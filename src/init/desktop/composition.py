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
"""Local geometry for the main orb and its expanding composer."""

from PySide6.QtCore import QEvent, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import QLayout, QWidget


class CompositionLayout(QLayout):
    MINIMUM_ORB = 96

    def __init__(self, parent):
        super().__init__(parent)
        self.items = []
        self.setContentsMargins(20, 12, 20, 20)
        self.setSpacing(16)

    def addItem(self, item):
        self.items.append(item)
        self.invalidate()

    def count(self):
        return len(self.items)

    def itemAt(self, index):
        return self.items[index] if 0 <= index < len(self.items) else None

    def takeAt(self, index):
        return self.items.pop(index) if 0 <= index < len(self.items) else None

    def expandingDirections(self):
        return Qt.Horizontal | Qt.Vertical

    def _height(self, item, width):
        hint = item.heightForWidth(width) if item.hasHeightForWidth() else item.sizeHint().height()
        return max(item.minimumSize().height(), min(item.maximumSize().height(), max(0, hint)))

    def _size(self, preferred):
        left, top, right, bottom = self.getContentsMargins()
        visible = [item for item in self.items if not item.isEmpty()]
        width = max((item.sizeHint().width() if preferred else item.minimumSize().width()
                     for item in visible[1:]), default=0)
        orb = self.items[0].sizeHint().width() if preferred and self.items else self.MINIMUM_ORB
        width = max(width, orb)
        height = orb + sum(self._height(item, width) for item in visible if item is not self.items[0])
        height += max(0, len(visible) - 1) * self.spacing()
        return QSize(width + left + right, height + top + bottom)

    def sizeHint(self):
        return self._size(True)

    def minimumSize(self):
        return self._size(False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        if not self.items:
            return
        area = self.contentsRect()
        tail = [item for item in self.items[1:] if not item.isEmpty()]
        heights = [self._height(item, area.width()) for item in tail]
        spacing = self.spacing()
        reserved = sum(heights) + spacing * len(tail)
        diameter = max(0, min(self.items[0].sizeHint().width(), area.width(),
                              area.height() - reserved))
        slack = max(0, area.height() - reserved - diameter)
        contextual = 0
        for item in tail:
            if item.widget() is None or not item.widget().property("orbContext"):
                break
            contextual += 1
        self.items[0].setGeometry(QRect(area.x() + (area.width() - diameter) // 2,
                                       area.y() + slack // 2, diameter, diameter))
        y = area.y() + slack // 2 + diameter
        for index, (item, height) in enumerate(zip(tail, heights)):
            if index == contextual:
                y += slack - slack // 2
            y += spacing
            item.setGeometry(QRect(area.x(), y, area.width(), height))
            y += height


class CompositionSurface(QWidget):
    minimum_changed = Signal(QSize)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._reported_minimum = QSize()

    def event(self, event):
        result = super().event(event)
        if event.type() == QEvent.LayoutRequest and self.layout() is not None:
            minimum = self.layout().minimumSize()
            if minimum != self._reported_minimum:
                self._reported_minimum = minimum
                self.minimum_changed.emit(minimum)
        return result
