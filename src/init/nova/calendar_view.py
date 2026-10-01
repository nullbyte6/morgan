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
"""Nova's calendar: week, month and year views over the reminder and event stores."""
from datetime import date, datetime, time

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from src.init.lang import tr
from src.init.theme import on_theme_changed

from . import formatting
from .calendar_math import MODES, MONTH, WEEK, month_grid, shift, visible_range, week_days
from .calendar_paint import (ALIGN_LEFT, CHEVRON_LEFT, CHEVRON_RIGHT, color, draw_chip, draw_text,
                             paint_month, text_font)
from .calendar_week import WeekPage
from .entries import Entry
from .store import NovaStore

MONTH_HEADER = 30
NARROW_WIDTH = 620
CHIP_HEIGHT = 19
CHIP_STEP = 21


def entries_by_day(entries: list[Entry], first: date, last: date) -> dict[date, list[Entry]]:
    days: dict[date, list[Entry]] = {}
    for entry in entries:
        for day in entry.days():
            if first <= day <= last:
                days.setdefault(day, []).append(entry)
    return days


class MonthGrid(QWidget):
    """A month of day cells, each listing as many entries as fit."""

    entry_activated = Signal(object)
    day_chosen = Signal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("novaMonthGrid")
        self.setMouseTracking(True)
        self.setMinimumSize(7 * 64, MONTH_HEADER + 5 * 84)
        self._day = date.today()
        self._today = date.today()
        self._by_day: dict[date, list[Entry]] = {}
        self._cells: list[tuple[QRect, date]] = []
        self._chips: list[tuple[QRect, Entry]] = []
        self._hovered_day: date | None = None
        self._hovered_entry: Entry | None = None
        on_theme_changed(self._theme_changed)

    def _theme_changed(self, _theme) -> None:
        self.update()

    def set_data(self, day: date, entries: list[Entry], today: date) -> None:
        self._day, self._today = day, today
        first, last = visible_range(day, MONTH, formatting.first_weekday())
        self._by_day = entries_by_day(entries, first, last)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        base = self.font()
        weeks = month_grid(self._day.year, self._day.month, formatting.first_weekday())
        width = self.width() / 7
        height = (self.height() - MONTH_HEADER) / len(weeks)
        for column in range(7):
            draw_text(painter, QRect(round(column * width), 0, round(width), MONTH_HEADER),
                      formatting.weekday_name((formatting.first_weekday() + column) % 7, "short"),
                      text_font(base, 12), "text_subtle", Qt.AlignmentFlag.AlignCenter)
        self._cells, self._chips = [], []
        for row, week in enumerate(weeks):
            for column, day in enumerate(week):
                cell = QRect(round(column * width), round(MONTH_HEADER + row * height),
                             round(width), round(height))
                self._cells.append((cell, day))
                self._paint_cell(painter, cell, day, base)
        painter.setPen(color("border", 150))
        for row in range(len(weeks) + 1):
            y = round(MONTH_HEADER + row * height)
            painter.drawLine(0, y, self.width(), y)
        for column in range(8):
            x = round(column * width)
            painter.drawLine(x, MONTH_HEADER, x, self.height())
        painter.end()

    def _paint_cell(self, painter: QPainter, cell: QRect, day: date, base) -> None:
        inside = day.month == self._day.month
        if day == self._hovered_day:
            painter.fillRect(cell, color("surface_raised", 150))
        elif not inside:
            painter.fillRect(cell, color("surface_sunken", 190))
        today = day == self._today
        disc = QRect(cell.left() + 6, cell.top() + 5, 24, 24)
        if today:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color("accent"))
            painter.drawEllipse(disc)
        draw_text(painter, disc, str(day.day), text_font(base, 12),
                  "on_accent" if today else ("text" if inside else "text_subtle"),
                  Qt.AlignmentFlag.AlignCenter)
        items = self._by_day.get(day, [])
        capacity = max(0, (cell.height() - 34) // CHIP_STEP)
        shown = items if len(items) <= capacity else items[:max(0, capacity - 1)]
        for index, entry in enumerate(shown):
            rect = QRect(cell.left() + 4, cell.top() + 33 + index * CHIP_STEP, cell.width() - 8, CHIP_HEIGHT)
            self._chips.append((rect, entry))
            draw_chip(painter, rect, entry, base, hovered=entry is self._hovered_entry, pixels=11)
        hidden = len(items) - len(shown)
        if hidden > 0:
            top = cell.top() + 33 + len(shown) * CHIP_STEP
            draw_text(painter, QRect(cell.left() + 8, top, cell.width() - 12, CHIP_HEIGHT),
                      tr("nova.calendar.more", count=hidden), text_font(base, 11), "text_muted", ALIGN_LEFT)

    def _cell_at(self, point: QPoint) -> date | None:
        return next((day for rect, day in self._cells if rect.contains(point)), None)

    def _entry_at(self, point: QPoint) -> Entry | None:
        return next((entry for rect, entry in self._chips if rect.contains(point)), None)

    def mouseMoveEvent(self, event):
        point = event.position().toPoint()
        hovered_entry, hovered_day = self._entry_at(point), self._cell_at(point)
        if hovered_entry is not self._hovered_entry or hovered_day != self._hovered_day:
            self._hovered_entry, self._hovered_day = hovered_entry, hovered_day
            self.setCursor(Qt.CursorShape.PointingHandCursor if hovered_day else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, event):
        self._hovered_entry = self._hovered_day = None
        self.update()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = event.position().toPoint()
        entry = self._entry_at(point)
        if entry is not None:
            self.entry_activated.emit(entry)
            return
        day = self._cell_at(point)
        if day is not None:
            self.day_chosen.emit(day)


class YearGrid(QWidget):
    """Twelve compact months; days with entries are tinted by how busy they are."""

    month_chosen = Signal(object)
    day_chosen = Signal(object)
    MONTH_HEIGHT = 190

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("novaYearGrid")
        self.setMouseTracking(True)
        policy = self.sizePolicy()
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self._year = date.today().year
        self._today = date.today()
        self._counts: dict[date, int] = {}
        self._hovered: date | None = None
        self._cells: list[tuple[QRect, date]] = []
        self._titles: list[tuple[QRect, date]] = []
        on_theme_changed(self._theme_changed)

    def _theme_changed(self, _theme) -> None:
        self.update()

    def columns(self, width: int | None = None) -> int:
        return max(2, min(4, (width or self.width()) // 230))

    def set_data(self, day: date, entries: list[Entry], today: date) -> None:
        self._year, self._today = day.year, today
        first, last = date(day.year, 1, 1), date(day.year, 12, 31)
        self._counts = {key: len(items) for key, items in entries_by_day(entries, first, last).items()}
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(4 * 230, 3 * self.MONTH_HEIGHT)

    def minimumSizeHint(self) -> QSize:
        return QSize(2 * 200, self.MONTH_HEIGHT)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return -(-12 // self.columns(width)) * self.MONTH_HEIGHT

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        base = self.font()
        columns = self.columns()
        width = self.width() / columns
        height = max(self.MONTH_HEIGHT, self.height() / -(-12 // columns))
        self._cells, self._titles = [], []
        for month in range(1, 13):
            row, column = divmod(month - 1, columns)
            rect = QRect(round(column * width) + 14, round(row * height) + 10,
                         round(width) - 28, round(height) - 20)
            cells, title = paint_month(
                painter, rect, self._year, month, base=base, first_weekday=formatting.first_weekday(),
                today=self._today, counts=self._counts, hovered=self._hovered)
            self._cells.extend(cells)
            self._titles.append((title, date(self._year, month, 1)))
        painter.end()

    def _day_at(self, point: QPoint) -> date | None:
        return next((day for rect, day in self._cells if rect.contains(point)), None)

    def _title_at(self, point: QPoint) -> date | None:
        return next((day for rect, day in self._titles if rect.contains(point)), None)

    def mouseMoveEvent(self, event):
        point = event.position().toPoint()
        hovered = self._day_at(point)
        if hovered != self._hovered:
            self._hovered = hovered
            self.update()
        clickable = hovered is not None or self._title_at(point) is not None
        self.setCursor(Qt.CursorShape.PointingHandCursor if clickable else Qt.CursorShape.ArrowCursor)

    def leaveEvent(self, event):
        self._hovered = None
        self.update()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = event.position().toPoint()
        day = self._day_at(point)
        if day is not None:
            self.day_chosen.emit(day)
            return
        month = self._title_at(point)
        if month is not None:
            self.month_chosen.emit(month)


class CalendarView(QWidget):
    """Week, month and year calendars with period navigation and drill-down between them."""

    entry_activated = Signal(object)
    create_requested = Signal(object)

    def __init__(self, store: NovaStore, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("novaCalendar")
        self._store = store
        self._mode = WEEK
        self._day = date.today()
        self._dirty = True

        self.title = QLabel()
        self.title.setObjectName("novaCalendarTitle")
        self.title.setMinimumWidth(0)
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.previous = self._arrow(CHEVRON_LEFT)
        self.next = self._arrow(CHEVRON_RIGHT)
        self.today_button = QPushButton()
        self.today_button.setObjectName("novaTodayButton")
        self.today_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.segments = QButtonGroup(self)
        self.segments.setExclusive(True)
        self._segment_buttons: dict[str, QPushButton] = {}

        navigation = QHBoxLayout()
        navigation.setSpacing(6)
        navigation.addWidget(self.previous)
        navigation.addWidget(self.today_button)
        navigation.addWidget(self.next)
        segments = QHBoxLayout()
        segments.setSpacing(6)
        for mode in MODES:
            button = QPushButton()
            button.setObjectName("novaSegment")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, mode=mode: self.set_mode(mode))
            self.segments.addButton(button)
            self._segment_buttons[mode] = button
            segments.addWidget(button)
        self._navigation, self._segments = QWidget(), QWidget()
        for holder, row in ((self._navigation, navigation), (self._segments, segments)):
            row.setContentsMargins(0, 0, 0, 0)
            holder.setLayout(row)
        self._header = QGridLayout()
        self._header.setContentsMargins(0, 0, 0, 0)
        self._header.setHorizontalSpacing(16)
        self._header.setVerticalSpacing(8)
        self._narrow: bool | None = None
        self._arrange_header(False)

        self.week = WeekPage()
        self.month = MonthGrid()
        self.year = YearGrid()
        self.stack = QStackedWidget()
        self.stack.addWidget(self.week)
        self.stack.addWidget(self._scrolling(self.month))
        self.stack.addWidget(self._scrolling(self.year))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addLayout(self._header)
        layout.addWidget(self.stack, 1)

        self.previous.clicked.connect(lambda: self.step(-1))
        self.next.clicked.connect(lambda: self.step(1))
        self.today_button.clicked.connect(self.go_today)
        self.week.entry_activated.connect(self.entry_activated)
        self.month.entry_activated.connect(self.entry_activated)
        self.week.create_requested.connect(self.create_requested)
        self.month.day_chosen.connect(self._open_week)
        self.year.day_chosen.connect(self._open_week)
        self.year.month_chosen.connect(self._open_month)
        store.changed.connect(self._store_changed)

        self.clock = QTimer(self)
        self.clock.setInterval(30_000)
        self.clock.timeout.connect(self.refresh)
        self.refresh_language()
        self._select_mode()

    @staticmethod
    def _scrolling(page: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setObjectName("novaScroll")
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.viewport().setAutoFillBackground(False)
        area.setWidget(page)
        return area

    @staticmethod
    def _arrow(glyph: str) -> QPushButton:
        button = QPushButton(glyph)
        button.setObjectName("novaArrow")
        button.setFixedSize(34, 34)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def _arrange_header(self, narrow: bool) -> None:
        """Put the period title above the controls when the view is too narrow for one row."""
        if narrow == self._narrow:
            return
        self._narrow = narrow
        for widget in (self.title, self._navigation, self._segments):
            self._header.removeWidget(widget)
        self._header.setColumnStretch(0, 0)
        self._header.setColumnStretch(1, 0)
        self._header.setColumnStretch(2, 0)
        if narrow:
            self._header.addWidget(self.title, 0, 0, 1, 2)
            self._header.addWidget(self._navigation, 1, 0)
            self._header.addWidget(self._segments, 1, 1, Qt.AlignmentFlag.AlignRight)
            self._header.setColumnStretch(1, 1)
        else:
            self._header.addWidget(self.title, 0, 0)
            self._header.addWidget(self._navigation, 0, 1)
            self._header.addWidget(self._segments, 0, 2)
            self._header.setColumnStretch(0, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange_header(self.width() < NARROW_WIDTH)

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def day(self) -> date:
        return self._day

    def set_mode(self, mode: str) -> None:
        if mode in MODES:
            self._mode = mode
            self._select_mode()
            self.refresh()

    def set_day(self, day: date) -> None:
        self._day = day
        self.refresh()

    def go_today(self) -> None:
        self.set_day(date.today())

    def step(self, direction: int) -> None:
        self.set_day(shift(self._day, self._mode, direction))

    def _select_mode(self) -> None:
        self.stack.setCurrentIndex(MODES.index(self._mode))
        self._segment_buttons[self._mode].setChecked(True)

    def _open_week(self, day: date) -> None:
        self._day = day
        self.set_mode(WEEK)

    def _open_month(self, day: date) -> None:
        self._day = day
        self.set_mode(MONTH)

    def _store_changed(self) -> None:
        if self.isVisible():
            self.refresh()
        else:
            self._dirty = True

    def refresh_language(self) -> None:
        for mode, button in self._segment_buttons.items():
            button.setText(tr(f"nova.calendar.{mode}"))
        self.today_button.setText(tr("nova.calendar.today"))
        self.previous.setToolTip(tr("nova.calendar.previous"))
        self.next.setToolTip(tr("nova.calendar.next"))
        self.refresh()

    def _title_text(self) -> str:
        if self._mode == WEEK:
            days = week_days(self._day, formatting.first_weekday())
            return formatting.week_title(days[0], days[-1])
        if self._mode == MONTH:
            return formatting.month_title(self._day)
        return str(self._day.year)

    def refresh(self) -> None:
        self._dirty = False
        first, last = visible_range(self._day, self._mode, formatting.first_weekday())
        entries = self._store.entries(first, last)
        now = datetime.now()
        self.title.setText(self._title_text())
        if self._mode == WEEK:
            self.week.set_data(week_days(self._day, formatting.first_weekday()), entries, now)
        elif self._mode == MONTH:
            self.month.set_data(self._day, entries, now.date())
        else:
            self.year.set_data(self._day, entries, now.date())

    def create_for(self, day: date) -> datetime:
        """The moment a new entry on day should start at: the next full hour today, else 09:00."""
        now = datetime.now()
        if day == now.date():
            return now.replace(minute=0, second=0, microsecond=0).replace(hour=min(23, now.hour + 1))
        return datetime.combine(day, time(9, 0))

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        self.clock.start()

    def hideEvent(self, event):
        self.clock.stop()
        super().hideEvent(event)
