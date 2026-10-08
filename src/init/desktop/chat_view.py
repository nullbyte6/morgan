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
"""Classic vertical chat view: the day's messages as speech bubbles that rise into place."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (Property, QEasingCurve, QPropertyAnimation, QRect, QRectF, QSize,
                            Qt, QTimer)
from PySide6.QtGui import QFontMetrics, QPainter, QPainterPath
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QScrollArea, QWidget

from src.init.lang import tr
from src.init.nova.messages import parse_log
from src.init.theme import current_theme, on_theme_changed

@dataclass(frozen=True)
class ChatMessage:
    role: str
    time: str
    text: str


def rounded_path(rect: QRectF, top_left: float, top_right: float,
                 bottom_right: float, bottom_left: float) -> QPainterPath:
    """Rounded rectangle whose four corners can have different radii."""
    path = QPainterPath()
    left, top, right, bottom = rect.left(), rect.top(), rect.right(), rect.bottom()
    cap = min(rect.width(), rect.height()) / 2
    top_left, top_right, bottom_right, bottom_left = (min(radius, cap) for radius in
                                                      (top_left, top_right, bottom_right, bottom_left))
    path.moveTo(left + top_left, top)
    path.lineTo(right - top_right, top)
    path.arcTo(QRectF(right - 2 * top_right, top, 2 * top_right, 2 * top_right), 90, -90)
    path.lineTo(right, bottom - bottom_right)
    path.arcTo(QRectF(right - 2 * bottom_right, bottom - 2 * bottom_right,
                      2 * bottom_right, 2 * bottom_right), 0, -90)
    path.lineTo(left + bottom_left, bottom)
    path.arcTo(QRectF(left, bottom - 2 * bottom_left, 2 * bottom_left, 2 * bottom_left), -90, -90)
    path.lineTo(left, top + top_left)
    path.arcTo(QRectF(left, top, 2 * top_left, 2 * top_left), 180, -90)
    path.closeSubpath()
    return path


class ChatBubble(QWidget):
    """One speech bubble, or a centered day label, that fades and slides up into its place."""
    RADIUS = 20
    TAIL_RADIUS = 6
    PADDING_X = 16
    PADDING_Y = 11
    CAPTION_GAP = 4
    RISE_MS = 520

    def __init__(self, role: str, time: str, text: str, parent: QWidget):
        super().__init__(parent)
        self.role = role
        self.time = time
        self.text = text
        self._rise = 1.0
        self._home = 0
        self._travel = 0
        self.effect = None
        self.animation = QPropertyAnimation(self, b"rise", self)
        self.animation.setDuration(self.RISE_MS)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.finished.connect(self._settled)
        self.delay = QTimer(self)
        self.delay.setSingleShot(True)
        self.delay.timeout.connect(self.animation.start)
        on_theme_changed(lambda theme: self.update())

    @Property(float)
    def rise(self):
        return self._rise

    @rise.setter
    def rise(self, value):
        self._rise = float(value)
        self.move(self.x(), self._home + round((1.0 - self._rise) * self._travel))
        if self.effect is not None:
            self.effect.setOpacity(min(1.0, self._rise * 1.4))

    def place(self, x: int, y: int, size: QSize, travel: int) -> None:
        self._home = y
        self._travel = travel
        self.setGeometry(x, y + round((1.0 - self._rise) * travel), size.width(), size.height())

    def rise_in(self, delay_ms: int) -> None:
        self.animation.stop()
        self.delay.stop()
        self.effect = QGraphicsOpacityEffect(self)
        self.effect.setOpacity(0.0)
        self.setGraphicsEffect(self.effect)
        self.rise = 0.0
        self.show()
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.delay.start(max(0, delay_ms))

    def settle(self) -> None:
        self.animation.stop()
        self.delay.stop()
        self.rise = 1.0
        self._settled()
        self.show()

    def _settled(self) -> None:
        if self._rise >= 1.0 and self.effect is not None:
            self.effect = None
            self.setGraphicsEffect(None)

    @property
    def home(self) -> int:
        return self._home

    @property
    def is_day(self) -> bool:
        return self.role == "day"

    def text_flags(self):
        return int(Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop)

    def measure(self, max_width: int) -> QSize:
        metrics = QFontMetrics(self.font())
        if self.is_day:
            return QSize(metrics.horizontalAdvance(self.text) + 24, metrics.height() + 10)
        limit = max_width - 2 * self.PADDING_X
        single = metrics.horizontalAdvance(self.text)
        if single <= limit:
            text_width, text_height = single + 2, metrics.height()
        else:
            bounds = metrics.boundingRect(QRect(0, 0, limit, 100000), self.text_flags(), self.text)
            text_width, text_height = limit, bounds.height()
        caption = self.caption_metrics()
        width = max(text_width, caption.horizontalAdvance(self.time)) + 2 * self.PADDING_X
        height = text_height + 2 * self.PADDING_Y + self.CAPTION_GAP + caption.height()
        return QSize(width, height)

    def caption_font(self):
        font = self.font()
        font.setPointSizeF(max(7.0, font.pointSizeF() * 0.8))
        return font

    def caption_metrics(self) -> QFontMetrics:
        return QFontMetrics(self.caption_font())

    def paintEvent(self, event):
        theme = current_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        if self.is_day:
            pill = QRectF(self.rect()).adjusted(1, 1, -1, -1)
            painter.setPen(theme.color("border", 90))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(pill, pill.height() / 2, pill.height() / 2)
            painter.setPen(theme.color("text_muted"))
            painter.drawText(self.rect(), Qt.AlignCenter, self.text)
            painter.end()
            return
        caption = self.caption_metrics()
        body = QRectF(0, 0, self.width(), self.height() - caption.height() - self.CAPTION_GAP)
        mine = self.role == "user"
        path = rounded_path(body.adjusted(1, 1, -1, -1), self.RADIUS, self.RADIUS,
                            self.TAIL_RADIUS if mine else self.RADIUS,
                            self.RADIUS if mine else self.TAIL_RADIUS)
        if mine:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.color("accent"))
            text_color = theme.color("on_accent")
        else:
            painter.setPen(theme.color("border"))
            painter.setBrush(theme.color("surface_raised"))
            text_color = theme.color("text")
        painter.drawPath(path)
        painter.setPen(text_color)
        painter.drawText(QRect(self.PADDING_X, self.PADDING_Y, self.width() - 2 * self.PADDING_X,
                               int(body.height()) - 2 * self.PADDING_Y), self.text_flags(), self.text)
        painter.setFont(self.caption_font())
        painter.setPen(theme.color("text_muted"))
        painter.drawText(QRect(4, int(body.height()) + self.CAPTION_GAP, self.width() - 8, caption.height()),
                         int((Qt.AlignRight if mine else Qt.AlignLeft) | Qt.AlignVCenter), self.time)
        painter.end()


class ChatView(QScrollArea):
    """Scrollable column of bubbles: assistant on the left, the user on the right."""
    MARGIN_X = 28
    MARGIN_Y = 12
    GAP = 10
    GROUP_GAP = 20
    MAX_BUBBLE = 620
    BUBBLE_RATIO = 0.74
    STAGGER_MS = 70
    STAGGERED = 12

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("chatView")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWidgetResizable(False)
        self.viewport().setAutoFillBackground(False)
        self.surface = QWidget()
        self.setWidget(self.surface)
        self.surface.setAutoFillBackground(False)
        self.bubbles: list[ChatBubble] = []
        self.setProperty("fillSlot", True)

    def set_messages(self, messages: list[ChatMessage], day_label: str = "") -> None:
        for bubble in self.bubbles:
            bubble.deleteLater()
        self.bubbles = []
        if day_label and messages:
            self.bubbles.append(ChatBubble("day", "", day_label, self.surface))
        for message in messages:
            self.bubbles.append(ChatBubble(message.role, message.time, message.text, self.surface))
        for bubble in self.bubbles:
            bubble.hide()
        self.relayout()

    def relayout(self) -> None:
        width = self.viewport().width()
        limit = min(self.MAX_BUBBLE, int(width * self.BUBBLE_RATIO))
        y = self.MARGIN_Y
        previous = None
        visible_bottom = self.verticalScrollBar().value() + self.viewport().height()
        for bubble in self.bubbles:
            size = bubble.measure(limit)
            if previous is not None:
                y += self.GROUP_GAP if previous.role != bubble.role or bubble.is_day else self.GAP
            if bubble.is_day:
                x = (width - size.width()) // 2
            elif bubble.role == "user":
                x = width - self.MARGIN_X - size.width()
            else:
                x = self.MARGIN_X
            bubble.place(x, y, size, max(80, visible_bottom - y))
            y += size.height()
            previous = bubble
        self.surface.resize(width, y + self.MARGIN_Y)

    def to_bottom(self) -> None:
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    def present(self) -> None:
        """Scroll to the newest message, then let the visible bubbles rise one after another."""
        self.relayout()
        self.to_bottom()
        self.relayout()
        top = self.verticalScrollBar().value()
        visible = [bubble for bubble in self.bubbles if bubble.home + bubble.height() > top]
        animated = visible[-self.STAGGERED:]
        for bubble in self.bubbles:
            if bubble in animated:
                bubble.rise_in(animated.index(bubble) * self.STAGGER_MS)
            else:
                bubble.settle()

    def dismiss(self) -> None:
        for bubble in self.bubbles:
            bubble.settle()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.relayout()


def day_messages(directory: Path, private: bool = False) -> list[ChatMessage]:
    """Today's user and assistant messages from the daily Markdown log; nothing for a private session."""
    if private:
        return []
    try:
        content = (Path(directory) / f"{datetime.now():%Y-%m-%d}.md").read_text(encoding="utf-8")
    except OSError:
        return []
    return [ChatMessage(message.role, message.timestamp[:5], message.content)
            for message in parse_log(content) if message.role in ("user", "assistant") and message.content.strip()]


def day_label() -> str:
    return tr("chat.today")
