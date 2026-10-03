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
"""Nova search: one box over reminders, events and the days of the diary."""
from datetime import date, datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QLabel, QLineEdit, QScrollArea, QVBoxLayout, QWidget

from src.init.lang import tr
from src.init.memory.integration import configured_service

from . import formatting
from .diary import clipped, local_moment, message_count
from .entries import Entry, Reminder
from .rows import EntryRow
from .store import NovaStore

DELAY_MS = 250
MESSAGE_LIMIT = 300


def _label(text: str, name: str, wrap: bool = True) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


class DayResult(QFrame):
    """A diary day with messages matching the search, opened in the diary when clicked."""

    activated = Signal(object)

    def __init__(self, day: date, excerpts: list[str], parent: QWidget | None = None):
        super().__init__(parent)
        self.day = day
        self.setObjectName("novaRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        column = QVBoxLayout(self)
        column.setContentsMargins(16, 13, 16, 13)
        column.setSpacing(3)
        column.addWidget(_label(formatting.day_heading(day), "novaRowTitle"))
        column.addWidget(_label(clipped(excerpts[0]), "novaRowNotes"))
        column.addWidget(_label(message_count(len(excerpts)), "novaRowCaption", wrap=False))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.activated.emit(self.day)
        super().mouseReleaseEvent(event)


class SearchView(QWidget):
    """A search box with the reminders, events and diary days that match it."""

    entry_activated = Signal(object)
    day_selected = Signal(object)

    def __init__(self, store: NovaStore, memory=configured_service, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("novaSearch")
        self._store = store
        self._memory = memory

        self.field = QLineEdit()
        self.field.setObjectName("novaInput")
        self.field.setClearButtonEnabled(True)

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
        layout.addWidget(self.field)
        layout.addWidget(self.scroll, 1)

        self._delay = QTimer(self)
        self._delay.setSingleShot(True)
        self._delay.setInterval(DELAY_MS)
        self._delay.timeout.connect(self.refresh)
        self.field.textChanged.connect(self._delay.start)
        self.field.returnPressed.connect(self.refresh)
        store.changed.connect(self._store_changed)
        self.refresh_language()

    def refresh_language(self) -> None:
        self.field.setPlaceholderText(tr("nova.search.placeholder"))
        self.refresh()

    def focus(self) -> None:
        self.field.setFocus()
        self.field.selectAll()

    def _store_changed(self) -> None:
        if self.isVisible():
            self.refresh()

    def _add(self, widget: QWidget) -> None:
        self._rows.insertWidget(self._rows.count() - 1, widget)

    def _days(self, query: str) -> tuple[dict[date, list[str]], str | None]:
        try:
            service = self._memory()
            if service is None:
                return {}, None
            rows = service.search_messages(query, limit=MESSAGE_LIMIT)
        except Exception as error:
            return {}, str(error)
        days: dict[date, list[str]] = {}
        for row in rows:
            days.setdefault(local_moment(row["created_at"]).date(), []).append(row["excerpt"])
        return days, None

    def refresh(self) -> None:
        self._delay.stop()
        while self._rows.count() > 1:
            widget = self._rows.takeAt(0).widget()
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        query = self.field.text().strip()
        if not query:
            self._add(_label(tr("nova.search.hint"), "novaDiaryNote"))
            return
        now = datetime.now()
        entries = self._store.search(query)
        groups: list[tuple[str, list[Entry]]] = [
            (tr("nova.section.reminders"), [entry for entry in entries if isinstance(entry, Reminder)]),
            (tr("nova.section.events"), [entry for entry in entries if not isinstance(entry, Reminder)])]
        for heading, found in groups:
            if not found:
                continue
            self._add(_label(heading, "novaGroup"))
            for entry in found:
                row = EntryRow(entry, now)
                row.activated.connect(self.entry_activated)
                row.toggled.connect(self._toggle_reminder)
                self._add(row)
        days, error = self._days(query)
        if days:
            self._add(_label(tr("nova.search.days"), "novaGroup"))
            for day in sorted(days, reverse=True):
                result = DayResult(day, days[day])
                result.activated.connect(self.day_selected)
                self._add(result)
        if error is not None:
            self._add(_label(tr("nova.diary.error", error=error), "novaDiaryNote"))
        elif not (entries or days):
            self._add(_label(tr("nova.search.empty", query=query), "novaDiaryNote"))

    def _toggle_reminder(self, entry: Entry, done: bool) -> None:
        if isinstance(entry, Reminder):
            self._store.set_reminder_completed(entry.id, done)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
