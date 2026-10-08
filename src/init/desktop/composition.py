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
    CHAT_ORB = 104

    def __init__(self, parent):
        super().__init__(parent)
        self.items = []
        self._chat = 0.0
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

    @staticmethod
    def _static(item):
        widget = item.widget()
        return widget is not None and bool(widget.property("staticSlot"))

    def _occupied(self, item):
        return not item.isEmpty() or self._static(item)

    def _height(self, item, width):
        if self._static(item):
            return item.widget().sizeHint().height()
        hint = item.heightForWidth(width) if item.hasHeightForWidth() else item.sizeHint().height()
        return max(item.minimumSize().height(), min(item.maximumSize().height(), max(0, hint)))

    def _size(self, preferred):
        left, top, right, bottom = self.getContentsMargins()
        visible = [item for item in self.items if self._occupied(item) and not self._fill(item)]
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

    @staticmethod
    def _fill(item):
        widget = item.widget()
        return widget is not None and bool(widget.property("fillSlot"))

    @staticmethod
    def _collapsing(item):
        widget = item.widget()
        return widget is not None and bool(widget.property("chatCollapse"))

    @property
    def chat(self):
        return self._chat

    @chat.setter
    def chat(self, value):
        self._chat = max(0.0, min(1.0, float(value)))
        self.invalidate()
        self.activate()

    def _resting(self, area, tail):
        """Orb centered in the free space, with the context below it and the composer at the bottom."""
        spacing = self.spacing()
        heights = [self._height(item, area.width()) for item in tail]
        reserved = sum(heights) + spacing * len(tail)
        diameter = max(0, min(self.items[0].sizeHint().width(), area.width(),
                              area.height() - reserved))
        slack = max(0, area.height() - reserved - diameter)
        contextual = 0
        for item in tail:
            if item.widget() is None or not item.widget().property("orbContext"):
                break
            contextual += 1
        top = area.y() + slack // 2
        rects = [QRect(area.x() + (area.width() - diameter) // 2, top, diameter, diameter)]
        y = top + diameter
        for index, height in enumerate(heights):
            if index == contextual:
                y += slack - slack // 2
            y += spacing
            rects.append(QRect(area.x(), y, area.width(), height))
            y += height
        return rects

    def _chatting(self, area, tail):
        """Small orb at the top, context under it, the fill slot taking the rest above the composer."""
        spacing = self.spacing()
        diameter = max(0, min(self.items[0].sizeHint().width(), self.CHAT_ORB, area.width()))
        heights = [None if self._fill(item) else 0 if self._collapsing(item)
                   else self._height(item, area.width()) for item in tail]
        gaps = sum(1 for height in heights if height != 0)
        free = area.height() - diameter - sum(height or 0 for height in heights) - spacing * gaps
        rects = [QRect(area.x() + (area.width() - diameter) // 2, area.y(), diameter, diameter)]
        y = area.y() + diameter
        for height in heights:
            if height != 0:
                y += spacing
            if height is None:
                height = max(0, free)
            rects.append(QRect(area.x(), y, area.width(), height))
            y += height
        return rects

    def setGeometry(self, rect):
        super().setGeometry(rect)
        if not self.items:
            return
        area = self.contentsRect()
        tail = [item for item in self.items[1:] if self._occupied(item)]
        stacked = [item for item in tail if not self._fill(item)]
        resting = self._resting(area, stacked)
        if self._chat <= 0.0 and len(stacked) == len(tail):
            for item, geometry in zip(self.items[:1] + stacked, resting):
                item.setGeometry(geometry)
            return
        chatting = self._chatting(area, tail)
        remaining = iter(resting[1:])
        resting_all = [resting[0]]
        for item in tail:
            resting_all.append(QRect(area.x(), resting[0].center().y(), area.width(), 0)
                               if self._fill(item) else next(remaining))
        progress = self._chat
        for item, start, end in zip(self.items[:1] + tail, resting_all, chatting):
            if self._fill(item):
                item.setGeometry(end)
                continue
            item.setGeometry(QRect(*(round(a + (b - a) * progress) for a, b in
                                     ((start.x(), end.x()), (start.y(), end.y()),
                                      (start.width(), end.width()), (start.height(), end.height())))))


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
