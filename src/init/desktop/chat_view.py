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

from PySide6.QtCore import (Property, QEasingCurve, QPointF, QPropertyAnimation, QRect, QRectF, QSize,
                            Qt, QTimer, Signal)
from PySide6.QtGui import QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QScrollArea, QWidget

from src.init.lang import tr
from src.init.nova.messages import parse_log
from src.init.theme import current_theme, theme_notifier

@dataclass(frozen=True)
class ChatMessage:
    role: str
    time: str
    text: str


class LiveText:
    """Subtitle phrases of one message joined as they arrive: a growing phrase is replaced in place."""

    def __init__(self):
        self.committed = ""
        self.current = ""

    @property
    def text(self) -> str:
        return " ".join(part for part in (self.committed, self.current) if part)

    def push(self, phrase: str) -> str:
        phrase = " ".join(str(phrase or "").split())
        if not phrase or phrase == self.current:
            return self.text
        if not self.current or not phrase.startswith(self.current):
            self.committed = self.text
        self.current = phrase
        return self.text


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

    @Property(float)
    def rise(self):
        return self._rise

    @rise.setter
    def rise(self, value):
        self._rise = float(value)
        self.move(self.x(), self._home + round((1.0 - self._rise) * self._travel))
        if self._rise < 1.0 and self.effect is None:
            self.effect = QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(self.effect)
        if self.effect is not None:
            self.effect.setOpacity(min(1.0, self._rise * 1.4))
        if self._rise >= 1.0 and self.animation.state() != QPropertyAnimation.State.Running:
            self._settled()

    def place(self, x: int, y: int, size: QSize, travel: int) -> None:
        self._home = y
        self._travel = travel
        self.setGeometry(x, y + round((1.0 - self._rise) * travel), size.width(), size.height())

    def rise_in(self, delay_ms: int) -> None:
        self.animation.stop()
        self.delay.stop()
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

    def set_text(self, text: str) -> None:
        self.text = text
        self.update()

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
    SPREAD = 0.45
    LEAVE = 0.5

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("chatView")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWidgetResizable(False)
        self.viewport().setAutoFillBackground(False)
        self.surface = QWidget()
        self.setWidget(self.surface)
        self.surface.setAutoFillBackground(False)
        self.bubbles: list[ChatBubble] = []
        self.live: ChatBubble | None = None
        self.day_label = ""
        self.entering: list[ChatBubble] = []
        self.pending = False
        self.leaving = False
        self.curve = QEasingCurve(QEasingCurve.Type.OutCubic)
        self.setProperty("fillSlot", True)
        theme_notifier().theme_changed.connect(self.apply_theme)

    def apply_theme(self, theme) -> None:
        """Repaint every bubble with the new theme's colors."""
        for bubble in self.bubbles:
            bubble.update()
        self.viewport().update()

    def set_messages(self, messages: list[ChatMessage], day_label: str = "") -> None:
        for bubble in self.bubbles:
            bubble.deleteLater()
        self.bubbles = []
        self.live = None
        self.day_label = day_label
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

    def set_live(self, role: str, text: str, animate: bool = True) -> None:
        """Show the message being spoken or written right now as the last bubble, growing as text arrives."""
        bar = self.verticalScrollBar()
        stick = bar.value() >= bar.maximum() - 8
        created = self.live is None or self.live.role != role
        if created:
            if not self.bubbles and self.day_label:
                self.bubbles.append(ChatBubble("day", "", self.day_label, self.surface))
                self.bubbles[-1].settle()
            self.live = ChatBubble(role, f"{datetime.now():%H:%M}", text, self.surface)
            self.bubbles.append(self.live)
        else:
            self.live.set_text(text)
        self.relayout()
        if stick:
            self.to_bottom()
            self.relayout()
        if created and animate:
            self.live.rise_in(0)

    def end_live(self) -> None:
        self.live = None

    def to_bottom(self) -> None:
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    def begin(self) -> None:
        """Hold every bubble back until the first frame of the orb animation has laid the view out."""
        self.pending = True
        self.leaving = False

    def prepare(self) -> None:
        """Scroll to the newest message and pick the bubbles on screen that follow the orb animation."""
        self.relayout()
        self.to_bottom()
        self.relayout()
        self.collect()

    def collect(self) -> None:
        top = self.verticalScrollBar().value()
        self.entering = [bubble for bubble in self.bubbles if bubble.home + bubble.height() > top]
        for bubble in self.bubbles:
            if bubble in self.entering:
                bubble.show()
            else:
                bubble.settle()

    def reveal(self, progress: float) -> None:
        """Fade and raise the visible bubbles with the orb animation, the oldest first and the newest last."""
        if self.pending:
            self.pending = False
            self.prepare()
        if self.leaving:
            for bubble in self.entering:
                bubble.rise = self.curve.valueForProgress(min(1.0, progress / self.LEAVE))
            return
        count = len(self.entering)
        span = 1.0 - self.SPREAD
        for index, bubble in enumerate(self.entering):
            start = self.SPREAD * index / max(1, count - 1)
            bubble.rise = self.curve.valueForProgress(min(1.0, max(0.0, (progress - start) / span)))

    def dismiss(self) -> None:
        """Take over the bubbles on screen, new ones included, so they leave with the orb coming back."""
        self.leaving = True
        if self.pending:
            self.pending = False
            self.prepare()
        else:
            self.collect()

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


class ViewToggle(QWidget):
    """Horizontal pill switching between the classic chat view (scroll) and the default orb view (star)."""

    clicked = Signal()
    WIDTH = 64
    HEIGHT = 30
    INSET = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("viewToggle")
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._chat = 0.0
        self.animation = QPropertyAnimation(self, b"chat", self)
        self.animation.setDuration(220)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        theme_notifier().theme_changed.connect(lambda *_: self.update())

    def get_chat(self) -> float:
        return self._chat

    def set_chat_value(self, value: float) -> None:
        self._chat = value
        self.update()

    chat = Property(float, get_chat, set_chat_value)

    def set_chat(self, opened: bool) -> None:
        self.animation.stop()
        self.animation.setStartValue(self._chat)
        self.animation.setEndValue(1.0 if opened else 0.0)
        self.animation.start()

    def mousePressEvent(self, event) -> None:
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()

    def paintEvent(self, event) -> None:
        theme = current_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        radius = self.HEIGHT / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.color("surface_selected"))
        painter.drawRoundedRect(QRectF(self.rect()), radius, radius)
        half = (self.WIDTH - 2 * self.INSET) / 2
        thumb = QRectF(self.INSET + (1.0 - self._chat) * half, self.INSET, half, self.HEIGHT - 2 * self.INSET)
        painter.setBrush(theme.color("accent"))
        painter.drawRoundedRect(thumb, thumb.height() / 2, thumb.height() / 2)
        for index, draw in enumerate((self.draw_scroll, self.draw_star)):
            weight = self._chat if index == 0 else 1.0 - self._chat
            role = "on_accent" if weight > 0.5 else "text_muted"
            side = 16
            cell = QRectF(self.INSET + index * half, self.INSET, half, self.HEIGHT - 2 * self.INSET)
            painter.save()
            painter.translate(cell.center().x() - side / 2, cell.center().y() - side / 2)
            painter.scale(side / 24, side / 24)
            pen = QPen(theme.color(role), 2.2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(theme.color(role) if draw == self.draw_star else Qt.BrushStyle.NoBrush)
            draw(painter)
            painter.restore()
        painter.end()

    @staticmethod
    def draw_scroll(painter) -> None:
        painter.drawRoundedRect(QRectF(6, 3, 12, 13), 2, 2)
        painter.drawRoundedRect(QRectF(3, 15, 16, 6), 3, 3)
        painter.drawLine(QPointF(9.5, 8), QPointF(14.5, 8))
        painter.drawLine(QPointF(9.5, 11.5), QPointF(14.5, 11.5))

    @staticmethod
    def draw_star(painter) -> None:
        star = QPainterPath()
        star.moveTo(12, 2.5)
        star.quadTo(13.2, 10.8, 21.5, 12)
        star.quadTo(13.2, 13.2, 12, 21.5)
        star.quadTo(10.8, 13.2, 2.5, 12)
        star.quadTo(10.8, 10.8, 12, 2.5)
        painter.drawPath(star)
