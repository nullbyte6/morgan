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
from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtWidgets import *

def compact_mascot_subtitle(text: str, limit: int = 64) -> str:
    """Return a single compact subtitle fragment capped at 'limit' chars."""
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[:limit - 1].rstrip() + "…"


class MascotSubtitleBubble(QWidget):
    """Animated, right-anchored subtitle ticker for the floating mascot."""
    WIDTH = 320
    GAP = 3
    PADDING_X = 12
    PADDING_Y = 10
    ANIMATION_MS = 120

    def __init__(self, mascot):
        super().__init__(None)
        self.mascot = mascot
        self._active = False

        self._source_text = ""
        self._visible_text = ""
        self._previous_text = ""
        self._offset = 0.0

        self.setObjectName("mascotSubtitleBubble")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self.setFixedWidth(self.WIDTH)
        self.setFixedHeight(
            self.fontMetrics().height() + self.PADDING_Y * 2 + 4
        )

        self.animation = QPropertyAnimation(self, b"offset", self)
        self.animation.setDuration(self.ANIMATION_MS)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.mascot.installEventFilter(self)
        self.hide()

    @Property(float)
    def offset(self):
        return self._offset

    @offset.setter
    def offset(self, value):
        self._offset = float(value)
        self.update()

    def _fit_text(self, text):
        """Keep the newest words within the available width."""
        metrics = self.fontMetrics()
        available = self.width() - self.PADDING_X * 2

        words = text.split()

        while len(words) > 1:
            candidate = " ".join(words)

            if metrics.horizontalAdvance(candidate) <= available:
                return candidate

            words.pop(0)

        if not words:
            return ""

        word = words[0]

        if metrics.horizontalAdvance(word) <= available:
            return word

        return metrics.elidedText(word, Qt.TextElideMode.ElideLeft,
            available)

    def set_subtitle(self, text: str, active: bool):
        """Receive the latest subtitle without changing the TTS pipeline."""
        subtitle = " ".join(str(text or "").split())
        self._active = bool(active and subtitle)

        if not self._active:
            self.animation.stop()
            self._source_text = ""
            self._visible_text = ""
            self._previous_text = ""
            self._offset = 0.0
            self.hide()
            return

        if subtitle != self._source_text:
            old_source = self._source_text
            old_visible = self._visible_text

            self._source_text = subtitle
            self._visible_text = self._fit_text(subtitle)

            appended = (
                bool(old_source)
                and subtitle.startswith(old_source)
                and len(subtitle) > len(old_source))
            self.animation.stop()

            if appended:
                metrics = self.fontMetrics()
                addition = subtitle[len(old_source):]
                distance = metrics.horizontalAdvance(addition)

                self._previous_text = old_visible
                self._offset = float(distance)
                self.animation.setStartValue(float(distance))
                self.animation.setEndValue(0.0)
                self.animation.start()

            else:
                self._previous_text = ""
                self._offset = 0.0

        if not self.mascot.isVisible():
            self.hide()
            return

        self.reposition()
        self.show()
        self.raise_()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        option = QStyleOption()
        option.initFrom(self)

        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget,
            option, painter, self)

        if not self._visible_text:
            painter.end()
            return

        metrics = self.fontMetrics()

        left = self.PADDING_X
        right = self.width() - self.PADDING_X
        top = self.PADDING_Y

        available = right - left
        painter.save()
        painter.setClipRect(QRectF(left, top, available,
                self.height() - self.PADDING_Y * 2))

        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        painter.setFont(self.font())

        baseline = ((self.height() - metrics.height()) / 2 + metrics.ascent())
        text_width = metrics.horizontalAdvance(self._visible_text)
        x = right - text_width + self._offset
        painter.drawText(QPointF(x, baseline),self._visible_text)

        painter.restore()
        painter.end()

    def reposition(self):
        screen = (QApplication.screenAt(self.mascot.frameGeometry().center())
            or QApplication.primaryScreen())
        if screen is None:
            return

        area = screen.availableGeometry()
        mascot = self.mascot.frameGeometry()
        bubble = self.frameGeometry()

        left_x = mascot.left() - bubble.width() - self.GAP
        right_x = mascot.right() + self.GAP + 1

        if left_x >= area.left():
            x = left_x
        else:
            x = min(right_x, area.right() - bubble.width() + 1)

        y = mascot.center().y() - bubble.height() // 2
        y = max(area.top(),min(y, area.bottom() - bubble.height() + 1))

        self.move(x, y)

    def eventFilter(self, watched, event):
        if watched is self.mascot:

            if event.type() in (QEvent.Type.Move, QEvent.Type.Resize):
                if self.isVisible():
                    self.reposition()

            elif event.type() == QEvent.Type.Show and self._active:
                QTimer.singleShot(0, self._show_for_mascot)

            elif event.type() == QEvent.Type.Hide:
                self.hide()

        return super().eventFilter(watched, event)

    def _show_for_mascot(self):
        if self._active and self.mascot.isVisible():
            self.reposition()
            self.show()
            self.raise_()
