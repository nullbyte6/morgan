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
"""The week in review: what got done, what is pending and what was talked about, summarised by the model."""
import threading
from datetime import date, datetime, timedelta

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from src.init.lang import tr
from src.init.memory.integration import configured_service

from . import formatting
from .calendar_paint import CHEVRON_LEFT, CHEVRON_RIGHT
from .entries import day_start
from .journal import clipped, day_bounds, describe_week, local_moment, summarize
from .store import NovaStore


def week_start(day: date) -> date:
    return day - timedelta(days=(day.weekday() - formatting.first_weekday()) % 7)


def _label(text: str, name: str, wrap: bool = True) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


class DayRow(QFrame):
    """A day of the week with activity, opened in the diary when clicked."""

    activated = Signal(object)

    def __init__(self, day: date, caption: str, topic: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.day = day
        self.setObjectName("novaRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        column = QVBoxLayout(self)
        column.setContentsMargins(16, 13, 16, 13)
        column.setSpacing(3)
        column.addWidget(_label(formatting.day_heading(day), "novaRowTitle"))
        if topic:
            column.addWidget(_label(clipped(topic), "novaRowNotes"))
        column.addWidget(_label(caption, "novaRowCaption", wrap=False))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.activated.emit(self.day)
        super().mouseReleaseEvent(event)


class ReviewView(QWidget):
    """One week at a time: reminders done and missed, events, conversations, memories and a model summary."""

    day_selected = Signal(object)
    summarized = Signal(object, str, bool)

    def __init__(self, store: NovaStore, memory=configured_service, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("novaReview")
        self._store = store
        self._memory = memory
        self._first = week_start(date.today())
        self._summaries: dict[date, tuple[str, bool]] = {}
        self._pending: set[date] = set()
        self._facts = ""

        self.previous = self._arrow(CHEVRON_LEFT)
        self.next = self._arrow(CHEVRON_RIGHT)
        self.week_label = QLabel()
        self.week_label.setObjectName("novaDiaryDay")
        self.week_label.setMinimumWidth(0)
        self.summarize_button = QPushButton()
        self.summarize_button.setObjectName("novaTodayButton")
        self.summarize_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.this_week_button = QPushButton()
        self.this_week_button.setObjectName("novaTodayButton")
        self.this_week_button.setCursor(Qt.CursorShape.PointingHandCursor)
        header = QHBoxLayout()
        header.setSpacing(6)
        header.addWidget(self.previous)
        header.addWidget(self.next)
        header.addSpacing(8)
        header.addWidget(self.week_label, 1)
        header.addWidget(self.summarize_button)
        header.addWidget(self.this_week_button)

        self._rows = QVBoxLayout()
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(8)
        self._rows.addStretch(1)
        body = QWidget()
        body.setObjectName("novaEntryBody")
        body.setLayout(self._rows)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("novaScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.setWidget(body)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addLayout(header)
        layout.addWidget(self.scroll, 1)

        self.previous.clicked.connect(lambda: self.set_week(self._first - timedelta(days=7)))
        self.next.clicked.connect(lambda: self.set_week(self._first + timedelta(days=7)))
        self.this_week_button.clicked.connect(lambda: self.set_week(date.today()))
        self.summarize_button.clicked.connect(self._summarize)
        self.summarized.connect(self._show_summary, Qt.ConnectionType.QueuedConnection)
        store.changed.connect(self._store_changed)
        self.refresh_language()

    @staticmethod
    def _arrow(glyph: str) -> QPushButton:
        button = QPushButton(glyph)
        button.setObjectName("novaArrow")
        button.setFixedSize(34, 34)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def set_week(self, day: date) -> None:
        self._first = week_start(day)
        self.refresh()

    def refresh_language(self) -> None:
        self.previous.setToolTip(tr("nova.calendar.previous"))
        self.next.setToolTip(tr("nova.calendar.next"))
        self.this_week_button.setText(tr("nova.review.this_week"))
        self.refresh()

    def _store_changed(self) -> None:
        if self.isVisible():
            self.refresh()

    def _add(self, widget: QWidget) -> None:
        self._rows.insertWidget(self._rows.count() - 1, widget)

    def _heading(self, text: str) -> None:
        self._add(_label(text, "novaGroup"))

    def _week(self) -> tuple[list, list, dict, str | None]:
        last = self._first + timedelta(days=6)
        reminders = self._store.reminders(day_start(self._first), day_start(last + timedelta(days=1)))
        events = self._store.events(self._first, last)
        data, error = {"sessions": [], "memories": []}, None
        try:
            service = self._memory()
            if service is not None:
                data = service.diary(day_bounds(self._first)[0], day_bounds(last)[1])
        except Exception as failure:
            error = str(failure)
        return reminders, events, data, error

    def refresh(self) -> None:
        now = datetime.now()
        last = self._first + timedelta(days=6)
        self.week_label.setText(formatting.week_title(self._first, last))
        busy = self._first in self._pending
        self.summarize_button.setText(tr("nova.review.summarizing" if busy else "nova.review.summarize"))
        while self._rows.count() > 1:
            widget = self._rows.takeAt(0).widget()
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        reminders, events, data, error = self._week()
        sessions = data["sessions"]
        active = bool(reminders or events or sessions or data["memories"])
        self.summarize_button.setEnabled(active and not busy)
        self._facts = describe_week(self._first, reminders, events, data, now) if active else ""

        summary = self._summaries.get(self._first)
        if summary is not None:
            text, failed = summary
            self._heading(tr("nova.review.summary"))
            card = QFrame()
            card.setObjectName("novaRow")
            column = QVBoxLayout(card)
            column.setContentsMargins(16, 13, 16, 13)
            column.addWidget(_label(tr("nova.review.summary_error", error=text) if failed else text,
                                    "novaRowNotes"))
            self._add(card)

        if active:
            done = sum(1 for reminder in reminders if reminder.is_completed)
            pending = sum(1 for reminder in reminders if not reminder.is_completed and reminder.remind_at >= now)
            self._heading(tr("nova.review.overview"))
            card = QFrame()
            card.setObjectName("novaRow")
            column = QVBoxLayout(card)
            column.setContentsMargins(16, 13, 16, 13)
            column.setSpacing(3)
            for text in (tr("nova.review.reminders", done=done, pending=pending,
                            missed=len(reminders) - done - pending),
                         tr("nova.review.events", count=len(events)),
                         tr("nova.review.conversations", count=len(sessions),
                            messages=sum(session["messages"] for session in sessions)),
                         tr("nova.review.memories", count=len(data["memories"]))):
                column.addWidget(_label(text, "novaRowTitle"))
            self._add(card)

        days: dict[date, dict] = {}
        for session in sessions:
            day = local_moment(session["started_at"]).date()
            info = days.setdefault(day, {"conversations": 0, "messages": 0, "entries": 0, "topic": ""})
            info["conversations"] += 1
            info["messages"] += session["messages"]
            info["topic"] = info["topic"] or session["topic"]
        for entry in [*reminders, *events]:
            for day in entry.days():
                if self._first <= day <= last:
                    days.setdefault(day, {"conversations": 0, "messages": 0, "entries": 0, "topic": ""})
                    days[day]["entries"] += 1
        if days:
            self._heading(tr("nova.review.days"))
            for day in sorted(days):
                info = days[day]
                row = DayRow(day, tr("nova.review.day_caption", conversations=info["conversations"],
                                     messages=info["messages"], entries=info["entries"]), info["topic"])
                row.activated.connect(self.day_selected)
                self._add(row)
        if error is not None:
            self._add(_label(tr("nova.diary.error", error=error), "novaDiaryNote"))
        elif not active:
            self._add(_label(tr("nova.review.empty"), "novaDiaryNote"))

    def _summarize(self) -> None:
        if not self._facts or self._first in self._pending:
            return
        first, facts = self._first, self._facts
        self._pending.add(first)
        self.refresh()

        def run() -> None:
            try:
                text, failed = summarize(facts), False
            except Exception as error:
                text, failed = str(error), True
            try:
                self.summarized.emit(first, text, failed)
            except RuntimeError:
                pass

        threading.Thread(target=run, name="nova-week-review", daemon=True).start()

    def _show_summary(self, first: date, text: str, failed: bool) -> None:
        self._pending.discard(first)
        self._summaries[first] = (text, failed)
        if first == self._first:
            self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
