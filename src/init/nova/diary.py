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
"""Arlo's diary: a day's agenda, memories and conversations, with every message shown as a log card."""
from datetime import date, datetime, timedelta
from getpass import getuser
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from src.init.config import HOME_PATH
from src.init.identity import get_assistant_name
from src.init.lang import tr
from src.init.memory.integration import configured_service

from . import formatting
from .calendar_paint import CHEVRON_LEFT, CHEVRON_RIGHT
from .entries import Entry, Reminder
from .journal import clipped, day_bounds, local_moment, message_count
from .messages import LogMessage, LogMessageCard, RemoveButton, code_font_family, parse_log
from .rows import EntryRow
from .store import NovaStore

CHEVRON_DOWN = "\U000f0140"
REFRESH_MS = 2000
COPIED_MS = 1200
MARKDOWN_SESSION = "markdown"


def stored_messages(rows: list[dict]) -> list[LogMessage]:
    """Database rows as log messages, named the way the daily log names its speakers."""
    authors = {"user": getuser().capitalize(), "assistant": get_assistant_name(), "system": "System"}
    return [LogMessage(timestamp=local_moment(row["created_at"]).strftime("%H:%M:%S"),
                       author=authors.get(row["role"], row["role"]), content=row["content"].strip("\n"),
                       role=row["role"], id=row["id"]) for row in rows]


def entry_markdown(entry: Entry) -> str:
    if isinstance(entry, Reminder):
        mark = "[x]" if entry.is_completed else "[ ]"
        line = f"- {mark} {formatting.time_text(entry.remind_at)} {entry.title}"
    else:
        line = f"- {formatting.event_time_text(entry)} {entry.title}"
    notes = "\n".join(f"  {text}" for text in entry.notes.splitlines() if text.strip())
    return f"{line}\n{notes}" if notes else line


def day_markdown(day: date, entries: list, memories: list[dict], conversations: list[tuple[dict, list]]) -> str:
    """One diary day as Markdown: the agenda, what was remembered and every message of each conversation."""
    parts = [f"# {formatting.day_heading(day)}"]
    if entries:
        parts.append(f"## {tr('nova.diary.agenda')}\n\n" + "\n".join(entry_markdown(entry) for entry in entries))
    if memories:
        parts.append(f"## {tr('nova.diary.learned')}\n\n"
                     + "\n".join(f"- {' '.join(memory['content'].split())}" for memory in memories))
    if conversations:
        parts.append(f"## {tr('nova.diary.conversations')}")
        for session, messages in conversations:
            topic = clipped(session["topic"]) or tr("nova.diary.untitled")
            parts.append(f"### {formatting.time_text(session['started'])} · {topic}")
            parts.extend(f"**{message.author}** · {message.timestamp}\n\n{message.content}" for message in messages)
    return "\n\n".join(parts) + "\n"


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
    """A conversation held that day; a click on its header unfolds every message as a log card."""

    def __init__(self, session: dict, loader, log_path: Path, forget=None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("novaRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.session_id = session["id"]
        self._loader = loader
        self._log_path = log_path
        self._forget = forget
        self._loaded = False
        span = formatting.time_text(session["started"])
        if session["ended"] - session["started"] >= timedelta(minutes=1):
            span += f" – {formatting.time_text(session['ended'])}"
        topic = clipped(session["topic"]) or tr("nova.diary.untitled")
        self._marker = QLabel(CHEVRON_RIGHT)
        self._marker.setObjectName("novaRowMarker")
        self._marker.setFixedWidth(24)
        head = QVBoxLayout()
        head.setSpacing(3)
        head.addWidget(_label(topic, "novaRowTitle"))
        head.addWidget(_label(f"{span} · {message_count(session['messages'])}", "novaRowCaption", wrap=False))
        self._head = QWidget()
        top = QHBoxLayout(self._head)
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(14)
        top.addWidget(self._marker, 0, Qt.AlignmentFlag.AlignTop)
        top.addLayout(head, 1)
        if forget is not None:
            remove = RemoveButton(code_font_family())
            remove.confirmed.connect(lambda: forget([message.id for message in loader(self.session_id)]))
            top.addWidget(remove, 0, Qt.AlignmentFlag.AlignTop)
        self._dialogue = QVBoxLayout()
        self._dialogue.setContentsMargins(0, 12, 0, 0)
        self._dialogue.setSpacing(10)
        self._body = QWidget()
        self._body.setLayout(self._dialogue)
        self._body.hide()
        column = QVBoxLayout(self)
        column.setContentsMargins(16, 13, 16, 13)
        column.setSpacing(0)
        column.addWidget(self._head)
        column.addWidget(self._body)

    @property
    def is_open(self) -> bool:
        return not self._body.isHidden()

    def set_open(self, opened: bool) -> None:
        if opened and not self._loaded:
            self._loaded = True
            family = code_font_family()
            for message in self._loader(self.session_id):
                card = LogMessageCard(message, self._log_path, family)
                if self._forget is not None:
                    card.removed.connect(lambda removed: self._forget([removed.id]))
                self._dialogue.addWidget(card)
        self._body.setVisible(opened)
        self._marker.setText(CHEVRON_DOWN if opened else CHEVRON_RIGHT)

    def _on_head(self, event) -> bool:
        return (event.button() == Qt.MouseButton.LeftButton
                and self._head.geometry().contains(event.position().toPoint()))

    def mousePressEvent(self, event):
        if self._on_head(event):
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._on_head(event):
            self.set_open(not self.is_open)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class DiaryView(QWidget):
    """One day of Arlo's life with you: the agenda, what it learned and every message exchanged."""

    entry_activated = Signal(object)

    def __init__(self, store: NovaStore, memory=configured_service, log_directory: Path | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("novaDiary")
        self._store = store
        self._memory = memory
        self._log_directory = Path(log_directory) if log_directory is not None else HOME_PATH / ".log"
        self._day = date.today()
        self._signature = None
        self._expanded: set[str] = set()
        self._contents = ([], [], [], None)

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
        self.copy_button = QPushButton()
        self.copy_button.setObjectName("novaTodayButton")
        self.copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.export_button = QPushButton()
        self.export_button.setObjectName("novaTodayButton")
        self.export_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_reset = QTimer(self)
        self.copy_reset.setSingleShot(True)
        self.copy_reset.setInterval(COPIED_MS)
        self.copy_reset.timeout.connect(lambda: self.copy_button.setText(tr("nova.diary.copy_day")))
        header = QHBoxLayout()
        header.setSpacing(6)
        header.addWidget(self.previous)
        header.addWidget(self.next)
        header.addSpacing(8)
        header.addWidget(self.day_label, 1)
        header.addWidget(self.copy_button)
        header.addWidget(self.export_button)
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
        self.copy_button.clicked.connect(self._copy_day)
        self.export_button.clicked.connect(self._export_day)
        store.changed.connect(self._store_changed)
        self.clock = QTimer(self)
        self.clock.setInterval(REFRESH_MS)
        self.clock.timeout.connect(self._tick)
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
        self.copy_button.setText(tr("nova.diary.copy_day"))
        self.copy_button.setToolTip(tr("nova.diary.copy_day_tooltip"))
        self.export_button.setText(tr("nova.diary.export_day"))
        self.export_button.setToolTip(tr("nova.diary.export_day_tooltip"))
        self.refresh()

    def _store_changed(self) -> None:
        if self.isVisible():
            self.refresh(force=False)

    def _tick(self) -> None:
        if self._day == date.today():
            self.refresh(force=False)

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

    def _log_path(self) -> Path:
        return self._log_directory / f"{self._day:%Y-%m-%d}.md"

    def _markdown_messages(self) -> list[LogMessage]:
        try:
            return parse_log(self._log_path().read_text(encoding="utf-8"))
        except OSError:
            return []

    def _sessions(self, service, data: dict) -> tuple[list[dict], object]:
        """The day's conversations and a loader for their messages: the database, else the daily log."""
        if service is not None and data["sessions"]:
            since, until = day_bounds(self._day)
            sessions = [{"id": row["session_id"], "started": local_moment(row["started_at"]),
                         "ended": local_moment(row["ended_at"]), "messages": row["messages"],
                         "topic": row["topic"]} for row in data["sessions"]]
            return sessions, lambda session_id: stored_messages(service.diary_messages(session_id, since, until))
        messages = self._markdown_messages()
        if not messages:
            return [], None
        stamps = [datetime.combine(self._day, datetime.strptime(message.timestamp, "%H:%M:%S").time())
                  for message in messages]
        topic = next((message.content for message in messages if message.role == "user"), "")
        return ([{"id": MARKDOWN_SESSION, "started": min(stamps), "ended": max(stamps),
                  "messages": len(messages), "topic": topic}],
                lambda _session_id: self._markdown_messages())

    def markdown(self) -> str:
        entries, memories, sessions, loader = self._contents
        conversations = [(session, loader(session["id"])) for session in sessions] if loader else []
        return day_markdown(self._day, entries, memories, conversations)

    def _copy_day(self) -> None:
        QApplication.clipboard().setText(self.markdown())
        self.copy_button.setText(tr("nova.diary.copied"))
        self.copy_reset.start()

    def _export_day(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(self, tr("nova.diary.export_day_tooltip"),
                                                    str(Path.home() / f"{self._day:%Y-%m-%d}.md"),
                                                    "Markdown (*.md)")
        if not path:
            return
        try:
            Path(path).write_text(self.markdown(), encoding="utf-8")
        except OSError as error:
            self._add(_label(tr("nova.diary.export_error", error=error), "novaDiaryNote"))

    def _forget(self, message_ids: list[str]) -> None:
        service, _error = self._service()
        if service is None:
            return
        try:
            service.forget_messages(message_ids)
        except Exception as error:
            self._add(_label(tr("nova.diary.error", error=error), "novaDiaryNote"))
            return
        self.refresh()

    def _heading(self, text: str) -> None:
        self._rows.insertWidget(self._rows.count() - 1, _label(text, "novaGroup"))

    def _add(self, widget: QWidget) -> None:
        self._rows.insertWidget(self._rows.count() - 1, widget)

    def refresh(self, force: bool = True) -> None:
        """Rebuild the page, unless nothing changed and force is off; unfolded conversations stay unfolded."""
        now = datetime.now()
        service, error = self._service()
        data = {"sessions": [], "memories": []}
        if service is not None:
            try:
                data = service.diary(*day_bounds(self._day))
            except Exception as failure:
                error = str(failure)
        sessions, loader = self._sessions(service, data)
        entries = self._store.entries(self._day, self._day)
        self._contents = (entries, data["memories"], sessions, loader)
        signature = (self._day, error, service is None, tuple(entries),
                     tuple(entry.id for entry in entries if isinstance(entry, Reminder)
                           and not entry.is_completed and entry.remind_at < now),
                     tuple((row["id"], row["modified_at"]) for row in data["memories"]),
                     tuple((row["id"], row["messages"], row["ended"]) for row in sessions))
        self.day_label.setText(formatting.day_heading(self._day))
        if not force and signature == self._signature:
            return
        same_day = self._signature is not None and self._signature[0] == self._day
        self._signature = signature
        scrollbar = self.scroll.verticalScrollBar()
        position = scrollbar.value() if same_day else 0
        at_bottom = same_day and scrollbar.value() >= scrollbar.maximum() - 20
        if same_day:
            for card in self.findChildren(ConversationCard):
                (self._expanded.add if card.is_open else self._expanded.discard)(card.session_id)
        else:
            self._expanded.clear()
        while self._rows.count() > 1:
            widget = self._rows.takeAt(0).widget()
            widget.setParent(None)
            widget.deleteLater()
        if entries:
            self._heading(tr("nova.diary.agenda"))
            for entry in entries:
                row = EntryRow(entry, now)
                row.activated.connect(self.entry_activated)
                row.toggled.connect(self._toggle_reminder)
                self._add(row)
        if data["memories"]:
            self._heading(tr("nova.diary.learned"))
            for memory in data["memories"]:
                self._add(MemoryCard(memory))
        if sessions:
            self._heading(tr("nova.diary.conversations"))
            for session in sessions:
                card = ConversationCard(session, loader, self._log_path(),
                                        None if session["id"] == MARKDOWN_SESSION else self._forget)
                self._add(card)
                if session["id"] in self._expanded:
                    card.set_open(True)
        if error is not None:
            self._add(_label(tr("nova.diary.error", error=error), "novaDiaryNote"))
        elif not (entries or data["memories"] or sessions):
            self._add(_label(tr("nova.diary.disabled" if service is None else "nova.diary.empty"),
                             "novaDiaryNote"))
        QTimer.singleShot(0, lambda: scrollbar.setValue(scrollbar.maximum() if at_bottom else position))

    def _toggle_reminder(self, entry: Entry, done: bool) -> None:
        if isinstance(entry, Reminder):
            self._store.set_reminder_completed(entry.id, done)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        self.clock.start()

    def hideEvent(self, event):
        self.clock.stop()
        super().hideEvent(event)
