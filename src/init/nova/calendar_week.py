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
"""The week view: a day header with an all-day strip above a scrolling hour grid."""
from datetime import date, datetime, time

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget

from src.init.theme import on_theme_changed

from . import formatting
from .calendar_math import assign_lanes
from .calendar_paint import (ALIGN_CENTER, ALIGN_RIGHT, color, draw_chip, draw_text, entry_role,
                             text_font, tint)
from .entries import Entry, Event, Reminder

HOUR_HEIGHT = 56
GUTTER = 58
DAY_HEADER = 66
STRIP_ROW = 24
MIN_BLOCK = 24
NOMINAL_MINUTES = 30
MINUTES_PER_DAY = 1440


def day_segments(day: date, entries: list[Entry]) -> list[tuple[Entry, int, int]]:
    """The timed pieces of entries that fall on one day, as (entry, start minute, end minute)."""
    segments = []
    for entry in entries:
        if isinstance(entry, Reminder):
            if entry.first_day == day:
                start = entry.remind_at.hour * 60 + entry.remind_at.minute
                segments.append((entry, start, start + NOMINAL_MINUTES))
        elif not entry.all_day and entry.spans(day):
            start = 0 if entry.starts_at.date() < day else entry.starts_at.hour * 60 + entry.starts_at.minute
            end = (MINUTES_PER_DAY if entry.ends_at.date() > day
                   else entry.ends_at.hour * 60 + entry.ends_at.minute)
            segments.append((entry, start, max(end, start + NOMINAL_MINUTES)))
    return [(entry, min(start, MINUTES_PER_DAY - NOMINAL_MINUTES), min(end, MINUTES_PER_DAY))
            for entry, start, end in segments]


def strip_rows(days: list[date], entries: list[Entry]) -> list[list[tuple[Event, int, int]]]:
    """Pack the all-day events of a week into rows of non-overlapping column spans."""
    spans = sorted(((entry, max(0, (entry.first_day - days[0]).days),
                     min(len(days) - 1, (entry.last_day - days[0]).days))
                    for entry in entries if isinstance(entry, Event) and entry.all_day),
                   key=lambda item: (item[1], -item[2], item[0].title.casefold()))
    rows: list[list[tuple[Event, int, int]]] = []
    for entry, first, last in spans:
        for row in rows:
            if row[-1][2] < first:
                row.append((entry, first, last))
                break
        else:
            rows.append([(entry, first, last)])
    return rows


class WeekHeader(QWidget):
    """Weekday names, day numbers and the strip of all-day events."""

    entry_activated = Signal(object)
    create_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("novaWeekHeader")
        self.setMouseTracking(True)
        self._days: list[date] = []
        self._rows: list[list[tuple[Event, int, int]]] = []
        self._today = date.today()
        self._hits: list[tuple[QRect, Event]] = []
        self._hovered: Event | None = None
        on_theme_changed(self._theme_changed)

    def _theme_changed(self, _theme) -> None:
        self.update()

    def required_height(self) -> int:
        return DAY_HEADER + (len(self._rows) * STRIP_ROW + 8 if self._rows else 0) + 1

    def set_data(self, days: list[date], entries: list[Entry], today: date) -> None:
        self._days, self._today = days, today
        self._rows = strip_rows(days, entries)
        self.setFixedHeight(self.required_height())
        self.update()

    def column_width(self) -> float:
        return (self.width() - GUTTER) / 7

    def paintEvent(self, event):
        if not self._days:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        base = self.font()
        width = self.column_width()
        for index, day in enumerate(self._days):
            left = GUTTER + index * width
            cell = QRect(round(left), 0, round(width), DAY_HEADER)
            today = day == self._today
            draw_text(painter, QRect(cell.left(), 10, cell.width(), 16),
                      formatting.weekday_name(day.weekday(), "short"), text_font(base, 12),
                      "accent" if today else "text_subtle", ALIGN_CENTER)
            disc = QRectF(cell.center().x() - 16, 28, 32, 32)
            if today:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color("accent"))
                painter.drawEllipse(disc)
            draw_text(painter, disc.toRect(), str(day.day), text_font(base, 18),
                      "on_accent" if today else "text", ALIGN_CENTER)
            painter.setPen(color("border", 150))
            painter.drawLine(round(left), 6, round(left), self.height())
        self._hits = []
        for row_index, row in enumerate(self._rows):
            for entry, first, last in row:
                rect = QRect(round(GUTTER + first * width) + 2, DAY_HEADER + 4 + row_index * STRIP_ROW,
                             round((last - first + 1) * width) - 4, STRIP_ROW - 3)
                self._hits.append((rect, entry))
                draw_chip(painter, rect, entry, base, hovered=entry is self._hovered)
        painter.setPen(color("border"))
        painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        painter.end()

    def _entry_at(self, point: QPoint) -> Event | None:
        return next((entry for rect, entry in self._hits if rect.contains(point)), None)

    def mouseMoveEvent(self, event):
        hovered = self._entry_at(event.position().toPoint())
        if hovered is not self._hovered:
            self._hovered = hovered
            self.setCursor(Qt.CursorShape.PointingHandCursor if hovered else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, event):
        self._hovered = None
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            entry = self._entry_at(event.position().toPoint())
            if entry is not None:
                self.entry_activated.emit(entry)

    def mouseDoubleClickEvent(self, event):
        point = event.position().toPoint()
        if self._entry_at(point) is not None or not self._days or point.x() < GUTTER:
            return
        index = min(6, int((point.x() - GUTTER) / max(1.0, self.column_width())))
        self.create_requested.emit(datetime.combine(self._days[index], time(9, 0)))


class WeekHours(QWidget):
    """The 24-hour grid with timed events, reminders and the current-time line."""

    entry_activated = Signal(object)
    create_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("novaWeekHours")
        self.setMouseTracking(True)
        self._days: list[date] = []
        self._entries: list[Entry] = []
        self._now = datetime.now()
        self._hits: list[tuple[QRect, Entry]] = []
        self._hovered: Entry | None = None
        self.setMinimumHeight(24 * HOUR_HEIGHT)
        on_theme_changed(self._theme_changed)

    def _theme_changed(self, _theme) -> None:
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(GUTTER + 7 * 90, 24 * HOUR_HEIGHT)

    def minimumSizeHint(self) -> QSize:
        return QSize(GUTTER + 7 * 48, 24 * HOUR_HEIGHT)

    def set_data(self, days: list[date], entries: list[Entry], now: datetime) -> None:
        self._days, self._entries, self._now = days, entries, now
        self.update()

    def column_width(self) -> float:
        return (self.width() - GUTTER) / 7

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        base = self.font()
        width = self.column_width()
        today = self._now.date()
        if today in self._days:
            painter.fillRect(QRect(round(GUTTER + self._days.index(today) * width), 0, round(width),
                                   self.height()), tint("accent", 14))
        painter.setPen(color("border", 90))
        for hour in range(24):
            painter.drawLine(GUTTER, hour * HOUR_HEIGHT, self.width(), hour * HOUR_HEIGHT)
        painter.setPen(color("border", 150))
        for index in range(8):
            x = round(GUTTER + index * width)
            painter.drawLine(x, 0, x, self.height())
        for hour in range(1, 24):
            draw_text(painter, QRect(0, hour * HOUR_HEIGHT - 8, GUTTER - 10, 16),
                      formatting.time_text(datetime(2000, 1, 1, hour)), text_font(base, 11),
                      "text_subtle", ALIGN_RIGHT)
        self._hits = []
        for index, day in enumerate(self._days):
            left = GUTTER + index * width
            for entry, start, end, lane, lanes in assign_lanes(day_segments(day, self._entries)):
                lane_width = (width - 6) / lanes
                top = start / 60 * HOUR_HEIGHT + 1
                real_end = (end if isinstance(entry, Event) else start) / 60 * HOUR_HEIGHT
                height = MIN_BLOCK if isinstance(entry, Reminder) else max(MIN_BLOCK, real_end - top - 1)
                rect = QRect(round(left + 3 + lane * lane_width), round(top),
                             max(8, round(lane_width) - 2), round(height))
                self._hits.append((rect, entry))
                self._paint_block(painter, rect, entry, base, entry is self._hovered)
        if today in self._days:
            y = round((self._now.hour * 60 + self._now.minute) / 60 * HOUR_HEIGHT)
            x = round(GUTTER + self._days.index(today) * width)
            painter.setPen(color("error"))
            painter.drawLine(x, y, round(x + width), y)
            painter.setBrush(color("error"))
            painter.drawEllipse(QPoint(x, y), 4, 4)
        painter.end()

    @staticmethod
    def _paint_block(painter: QPainter, rect: QRect, entry: Entry, base, hovered: bool) -> None:
        if isinstance(entry, Reminder) or rect.height() < 34:
            draw_chip(painter, rect, entry, base, hovered=hovered)
            return
        role = entry_role(entry)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(tint(role, 90 if hovered else 62))
        painter.drawRoundedRect(QRectF(rect), 6, 6)
        painter.setBrush(color(role))
        painter.drawRoundedRect(QRectF(rect.left(), rect.top() + 3, 3, rect.height() - 6), 1.5, 1.5)
        inner = rect.adjusted(10, 5, -6, -4)
        draw_text(painter, QRect(inner.left(), inner.top(), inner.width(), 16), entry.title,
                  text_font(base, 12), "text")
        draw_text(painter, QRect(inner.left(), inner.top() + 16, inner.width(), 15),
                  formatting.event_time_text(entry), text_font(base, 11), "text_muted")

    def _entry_at(self, point: QPoint) -> Entry | None:
        return next((entry for rect, entry in reversed(self._hits) if rect.contains(point)), None)

    def mouseMoveEvent(self, event):
        hovered = self._entry_at(event.position().toPoint())
        if hovered is not self._hovered:
            self._hovered = hovered
            self.setCursor(Qt.CursorShape.PointingHandCursor if hovered else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, event):
        self._hovered = None
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            entry = self._entry_at(event.position().toPoint())
            if entry is not None:
                self.entry_activated.emit(entry)

    def mouseDoubleClickEvent(self, event):
        point = event.position().toPoint()
        if self._entry_at(point) is not None or not self._days or point.x() < GUTTER:
            return
        index = min(6, int((point.x() - GUTTER) / max(1.0, self.column_width())))
        minutes = min(MINUTES_PER_DAY - 30, int(point.y() / HOUR_HEIGHT * 60) // 30 * 30)
        self.create_requested.emit(datetime.combine(self._days[index], time(minutes // 60, minutes % 60)))


class WeekPage(QWidget):
    """A fixed day header over an hour grid that scrolls vertically."""

    entry_activated = Signal(object)
    create_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.header = WeekHeader(self)
        self.hours = WeekHours()
        self.scroll = QScrollArea(self)
        self.scroll.setObjectName("novaScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.hours)
        self.scroll.viewport().setAutoFillBackground(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        layout.addWidget(self.scroll, 1)
        for source in (self.header, self.hours):
            source.entry_activated.connect(self.entry_activated)
            source.create_requested.connect(self.create_requested)
        self._scrolled_for: date | None = None

    def set_data(self, days: list[date], entries: list[Entry], now: datetime) -> None:
        self.header.set_data(days, entries, now.date())
        self.hours.set_data(days, entries, now)
        if self._scrolled_for != days[0]:
            self._scrolled_for = days[0]
            QTimer.singleShot(0, lambda: self.scroll_to_hour(now.hour - 2 if now.date() in days else 7))

    def scroll_to_hour(self, hour: int) -> None:
        self.scroll.verticalScrollBar().setValue(max(0, hour) * HOUR_HEIGHT)
