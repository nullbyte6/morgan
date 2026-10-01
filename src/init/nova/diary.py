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
"""Arlo's diary: the memory database presented one day at a time."""
from datetime import date, datetime, time, timedelta, timezone

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from src.init.identity import get_assistant_name
from src.init.lang import tr
from src.init.memory.integration import configured_service

from . import formatting
from .calendar_paint import CHEVRON_LEFT, CHEVRON_RIGHT
from .entries import Entry, Reminder
from .rows import EntryRow
from .store import NovaStore

CHEVRON_DOWN = "\U000f0140"
TOPIC_LIMIT = 140
MESSAGE_LIMIT = 1200


def day_bounds(day: date) -> tuple[str, str]:
    """The local day as UTC ISO timestamps, the form the memory database stores."""
    start = datetime.combine(day, time.min).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time.min).astimezone(timezone.utc)
    return start.isoformat(timespec="microseconds"), end.isoformat(timespec="microseconds")


def local_moment(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp).astimezone().replace(tzinfo=None)


def clipped(text: str, limit: int) -> str:
    text = " ".join(text.split()) if limit == TOPIC_LIMIT else text.strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def message_count(count: int) -> str:
    return tr("nova.diary.message_one") if count == 1 else tr("nova.diary.messages", count=count)


def _label(text: str, name: str, wrap: bool = True) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


class MemoryCard(QFrame):
    """One thing Arlo remembers, with its kind and when it was last written."""

    def __init__(self, memory: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("novaRow")
        column = QVBoxLayout(self)
        column.setContentsMargins(16, 13, 16, 13)
        column.setSpacing(3)
        column.addWidget(_label(memory["content"], "novaRowTitle"))
        category = tr(f"nova.diary.category.{memory['category']}")
        when = formatting.time_text(local_moment(memory["modified_at"]))
        column.addWidget(_label(f"{category} · {when}", "novaRowCaption", wrap=False))


class ConversationCard(QFrame):
    """A conversation held that day; a click unfolds what was said."""

    def __init__(self, session: dict, loader, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("novaRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._session_id = session["session_id"]
        self._loader = loader
        self._loaded = False
        started, ended = local_moment(session["started_at"]), local_moment(session["ended_at"])
        span = formatting.time_text(started)
        if ended - started >= timedelta(minutes=1):
            span += f" – {formatting.time_text(ended)}"
        topic = clipped(session["topic"], TOPIC_LIMIT) or tr("nova.diary.untitled")
        self._marker = QLabel(CHEVRON_RIGHT)
        self._marker.setObjectName("novaRowMarker")
        self._marker.setFixedWidth(24)
        head = QVBoxLayout()
        head.setSpacing(3)
        head.addWidget(_label(topic, "novaRowTitle"))
        head.addWidget(_label(f"{span} · {message_count(session['messages'])}", "novaRowCaption", wrap=False))
        top = QHBoxLayout()
        top.setSpacing(14)
        top.addWidget(self._marker, 0, Qt.AlignmentFlag.AlignTop)
        top.addLayout(head, 1)
        self._dialogue = QVBoxLayout()
        self._dialogue.setContentsMargins(38, 6, 0, 0)
        self._dialogue.setSpacing(10)
        self._body = QWidget()
        self._body.setLayout(self._dialogue)
        self._body.hide()
        column = QVBoxLayout(self)
        column.setContentsMargins(16, 13, 16, 13)
        column.setSpacing(0)
        column.addLayout(top)
        column.addWidget(self._body)

    def _load(self) -> None:
        self._loaded = True
        you, arlo = tr("nova.diary.you"), get_assistant_name()
        for message in self._loader(self._session_id):
            role = "assistant" if message["role"] == "assistant" else "user"
            who = f"{arlo if role == 'assistant' else you} · {formatting.time_text(local_moment(message['created_at']))}"
            header = _label(who, "novaDiaryRole", wrap=False)
            header.setProperty("role", role)
            self._dialogue.addWidget(header)
            self._dialogue.addWidget(_label(clipped(message["content"], MESSAGE_LIMIT), "novaDiaryMessage"))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            if not self._loaded:
                self._load()
            opened = not self._body.isVisible()
            self._body.setVisible(opened)
            self._marker.setText(CHEVRON_DOWN if opened else CHEVRON_RIGHT)
        super().mouseReleaseEvent(event)


class DiaryView(QWidget):
    """One day of Arlo's life with you: the agenda, what it learned and what you talked about."""

    entry_activated = Signal(object)

    def __init__(self, store: NovaStore, memory=configured_service, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("novaDiary")
        self._store = store
        self._memory = memory
        self._day = date.today()

        self.previous = self._arrow(CHEVRON_LEFT)
        self.next = self._arrow(CHEVRON_RIGHT)
        self.day_label = QLabel()
        self.day_label.setObjectName("novaDiaryDay")
        self.day_label.setMinimumWidth(0)
        self.earlier_button = QPushButton()
        self.earlier_button.setObjectName("novaTodayButton")
        self.earlier_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.today_button = QPushButton()
        self.today_button.setObjectName("novaTodayButton")
        self.today_button.setCursor(Qt.CursorShape.PointingHandCursor)
        header = QHBoxLayout()
        header.setSpacing(6)
        header.addWidget(self.previous)
        header.addWidget(self.next)
        header.addSpacing(8)
        header.addWidget(self.day_label, 1)
        header.addWidget(self.earlier_button)
        header.addWidget(self.today_button)

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

        self.previous.clicked.connect(lambda: self.set_day(self._day - timedelta(days=1)))
        self.next.clicked.connect(lambda: self.set_day(self._day + timedelta(days=1)))
        self.today_button.clicked.connect(lambda: self.set_day(date.today()))
        self.earlier_button.clicked.connect(self._jump_earlier)
        store.changed.connect(self._store_changed)
        self._dirty = True
        self.refresh_language()

    @staticmethod
    def _arrow(glyph: str) -> QPushButton:
        button = QPushButton(glyph)
        button.setObjectName("novaArrow")
        button.setFixedSize(34, 34)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    @property
    def day(self) -> date:
        return self._day

    def set_day(self, day: date) -> None:
        self._day = day
        self.refresh()

    def refresh_language(self) -> None:
        self.previous.setToolTip(tr("nova.calendar.previous"))
        self.next.setToolTip(tr("nova.calendar.next"))
        self.earlier_button.setText(tr("nova.diary.previous_entry"))
        self.today_button.setText(tr("nova.calendar.today"))
        self.refresh()

    def _store_changed(self) -> None:
        if self.isVisible():
            self.refresh()
        else:
            self._dirty = True

    def _service(self):
        try:
            return self._memory(), None
        except Exception as error:
            return None, str(error)

    def _jump_earlier(self) -> None:
        service, _error = self._service()
        if service is None:
            return
        try:
            stamp = service.adjacent_activity(day_bounds(self._day)[0], earlier=True)
        except Exception:
            return
        if stamp is not None:
            self.set_day(local_moment(stamp).date())

    def _loader(self, service):
        since, until = day_bounds(self._day)
        return lambda session_id: service.diary_messages(session_id, since, until)

    def _heading(self, text: str) -> None:
        self._rows.insertWidget(self._rows.count() - 1, _label(text, "novaGroup"))

    def _add(self, widget: QWidget) -> None:
        self._rows.insertWidget(self._rows.count() - 1, widget)

    def refresh(self) -> None:
        self._dirty = False
        self.day_label.setText(formatting.day_heading(self._day))
        position = self.scroll.verticalScrollBar().value()
        while self._rows.count() > 1:
            widget = self._rows.takeAt(0).widget()
            widget.setParent(None)
            widget.deleteLater()
        service, error = self._service()
        data = {"sessions": [], "memories": []}
        if service is not None:
            try:
                data = service.diary(*day_bounds(self._day))
            except Exception as failure:
                error = str(failure)
        entries = self._store.entries(self._day, self._day)
        if entries:
            self._heading(tr("nova.diary.agenda"))
            now = datetime.now()
            for entry in entries:
                row = EntryRow(entry, now)
                row.activated.connect(self.entry_activated)
                row.toggled.connect(self._toggle_reminder)
                self._add(row)
        if data["memories"]:
            self._heading(tr("nova.diary.learned"))
            for memory in data["memories"]:
                self._add(MemoryCard(memory))
        if data["sessions"]:
            self._heading(tr("nova.diary.conversations"))
            for session in data["sessions"]:
                self._add(ConversationCard(session, self._loader(service)))
        if error is not None:
            self._add(_label(tr("nova.diary.error", error=error), "novaDiaryNote"))
        elif service is None:
            self._add(_label(tr("nova.diary.disabled"), "novaDiaryNote"))
        elif not (entries or data["memories"] or data["sessions"]):
            self._add(_label(tr("nova.diary.empty"), "novaDiaryNote"))
        scrollbar = self.scroll.verticalScrollBar()
        QTimer.singleShot(0, lambda: scrollbar.setValue(position))

    def _toggle_reminder(self, entry: Entry, done: bool) -> None:
        if isinstance(entry, Reminder):
            self._store.set_reminder_completed(entry.id, done)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
