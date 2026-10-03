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
"""Nova's reminders and events, stored without any interface toolkit so every version can use them."""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path

from src.init.config import HOME_PATH
from src.init.memory.database import timestamp

from .database import EventDatabase, ReminderDatabase
from .entries import (Entry, Event, FLAGS, NOTES_LIMIT, Reminder, TITLE_LIMIT, day_start,
                      next_occurrence, normalize_recurrence, parse_recurrence, to_local)


def _text(title: str, notes: str) -> tuple[str, str]:
    title = " ".join(str(title).split())
    notes = str(notes).strip()
    if not 1 <= len(title) <= TITLE_LIMIT:
        raise ValueError(f"The title must contain 1-{TITLE_LIMIT} characters")
    if len(notes) > NOTES_LIMIT:
        raise ValueError(f"The notes must not exceed {NOTES_LIMIT} characters")
    return title, notes


def _recurrence(value: str, all_day: bool = False) -> str:
    value = normalize_recurrence(value)
    parsed = parse_recurrence(value)
    if all_day and parsed is not None and parsed[1] == "hours":
        raise ValueError("An all-day event cannot repeat by the hour")
    return value


def _flag(value: str) -> str:
    value = str(value or "none").strip().casefold()
    if value not in FLAGS:
        raise ValueError("The flag must be none, green, yellow or red")
    return value


def _span(starts_at: datetime, ends_at: datetime, all_day: bool) -> tuple[str, str]:
    if all_day:
        starts_at = day_start(starts_at.date())
        ends_at = datetime.combine(ends_at.date(), time(23, 59))
    if ends_at < starts_at:
        raise ValueError("The event cannot end before it starts")
    return to_local(starts_at), to_local(ends_at)


class NovaRecords:
    """Reminders and events in two separate SQLite databases, telling listeners when they change."""

    def __init__(self, directory: Path | str | None = None):
        self.open(directory)

    def open(self, directory: Path | str | None = None) -> None:
        directory = Path(directory) if directory is not None else HOME_PATH / "nova"
        self.reminder_db = ReminderDatabase(directory / "reminders.sqlite3")
        self.event_db = EventDatabase(directory / "events.sqlite3")
        self._listeners = []

    def subscribe(self, listener) -> None:
        """Call listener, from the thread that made the change, whenever an entry changes."""
        self._listeners.append(listener)

    def _changed(self) -> None:
        for listener in list(self._listeners):
            listener()

    def add_reminder(self, title: str, remind_at: datetime, notes: str = "",
                     recurrence: str = "none", flag: str = "none") -> Reminder:
        title, notes = _text(title, notes)
        recurrence, flag = _recurrence(recurrence), _flag(flag)
        reminder_id = uuid.uuid4().hex
        with self.reminder_db.connect(write=True) as db:
            db.execute("""INSERT INTO reminders(id,title,notes,remind_at,created_at,recurrence,flag)
                VALUES(?,?,?,?,?,?,?)""",
                       (reminder_id, title, notes, to_local(remind_at), timestamp(), recurrence, flag))
        self._changed()
        return self.reminder(reminder_id)

    def update_reminder(self, reminder_id: str, title: str, remind_at: datetime,
                        notes: str = "", recurrence: str = "none", flag: str = "none") -> Reminder:
        title, notes = _text(title, notes)
        recurrence, flag = _recurrence(recurrence), _flag(flag)
        moment = to_local(remind_at)
        with self.reminder_db.connect(write=True) as db:
            updated = db.execute(
                """UPDATE reminders SET title=?,notes=?,recurrence=?,flag=?,
                notified_at=CASE WHEN remind_at<>? THEN NULL ELSE notified_at END,
                remind_at=? WHERE id=?""",
                (title, notes, recurrence, flag, moment, moment, reminder_id)).rowcount
        if not updated:
            raise ValueError("The reminder no longer exists")
        self._changed()
        return self.reminder(reminder_id)

    def set_reminder_completed(self, reminder_id: str, completed: bool) -> Reminder:
        """Complete or reopen a reminder; completing a repeating one moves it to its next time instead."""
        current = self.reminder(reminder_id)
        if current is None:
            raise ValueError("The reminder no longer exists")
        with self.reminder_db.connect(write=True) as db:
            if completed and current.is_recurring:
                after = max(current.remind_at, datetime.now())
                db.execute("UPDATE reminders SET remind_at=?,notified_at=NULL,completed_at=NULL WHERE id=?",
                           (to_local(next_occurrence(current.remind_at, current.recurrence, after)), reminder_id))
            else:
                db.execute("UPDATE reminders SET completed_at=? WHERE id=?",
                           (timestamp() if completed else None, reminder_id))
        self._changed()
        return self.reminder(reminder_id)

    def snooze_reminder(self, reminder_id: str, until: datetime) -> Reminder:
        """Remind again at until: a one-off reminder moves there, a repeating one gets a one-off copy
        unless its next repetition already comes by then."""
        current = self.reminder(reminder_id)
        if current is None:
            raise ValueError("The reminder no longer exists")
        if current.is_recurring:
            if current.remind_at <= until:
                return current
            return self.add_reminder(current.title, until, current.notes, flag=current.flag)
        with self.reminder_db.connect(write=True) as db:
            db.execute("UPDATE reminders SET remind_at=?,notified_at=NULL,completed_at=NULL WHERE id=?",
                       (to_local(until), reminder_id))
        self._changed()
        return self.reminder(reminder_id)

    def delete_reminder(self, reminder_id: str) -> bool:
        with self.reminder_db.connect(write=True) as db:
            deleted = db.execute("DELETE FROM reminders WHERE id=?", (reminder_id,)).rowcount == 1
        if deleted:
            self._changed()
        return deleted

    def reminder(self, reminder_id: str) -> Reminder | None:
        with self.reminder_db.connect() as db:
            row = db.execute("SELECT * FROM reminders WHERE id=?", (reminder_id,)).fetchone()
        return Reminder.from_row(row) if row else None

    def reminders(self, start: datetime | None = None, end: datetime | None = None,
                  completed: bool | None = None) -> list[Reminder]:
        """Reminders due in [start, end), optionally only completed or only pending ones."""
        clauses, values = [], []
        if start is not None:
            clauses.append("remind_at >= ?")
            values.append(to_local(start))
        if end is not None:
            clauses.append("remind_at < ?")
            values.append(to_local(end))
        if completed is not None:
            clauses.append("completed_at IS NOT NULL" if completed else "completed_at IS NULL")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.reminder_db.connect() as db:
            rows = db.execute(f"SELECT * FROM reminders{where} ORDER BY remind_at,created_at,id", values)
            return [Reminder.from_row(row) for row in rows]

    def overdue(self, now: datetime | None = None) -> list[Reminder]:
        return self.reminders(end=now or datetime.now(), completed=False)

    def pop_due(self, now: datetime | None = None) -> list[Reminder]:
        """Return every pending reminder due by now, including missed ones, marking one-off reminders
        as notified and moving repeating ones to their next time."""
        now = now or datetime.now()
        limit = to_local(now)
        with self.reminder_db.connect(write=True) as db:
            rows = db.execute("""SELECT * FROM reminders WHERE completed_at IS NULL
                AND notified_at IS NULL AND remind_at <= ? ORDER BY remind_at,id""", (limit,)).fetchall()
            due = [Reminder.from_row(row) for row in rows]
            for reminder in due:
                if reminder.is_recurring:
                    db.execute("UPDATE reminders SET remind_at=? WHERE id=?",
                               (to_local(next_occurrence(reminder.remind_at, reminder.recurrence, now)),
                                reminder.id))
                else:
                    db.execute("UPDATE reminders SET notified_at=? WHERE id=?", (timestamp(), reminder.id))
        if any(reminder.is_recurring for reminder in due):
            self._changed()
        return due

    def add_event(self, title: str, starts_at: datetime, ends_at: datetime, *,
                  all_day: bool = False, notes: str = "", recurrence: str = "none",
                  flag: str = "none") -> Event:
        title, notes = _text(title, notes)
        starts, ends = _span(starts_at, ends_at, all_day)
        recurrence, flag = _recurrence(recurrence, all_day), _flag(flag)
        event_id = uuid.uuid4().hex
        with self.event_db.connect(write=True) as db:
            db.execute("""INSERT INTO events(id,title,notes,starts_at,ends_at,all_day,created_at,recurrence,flag)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                       (event_id, title, notes, starts, ends, int(all_day), timestamp(), recurrence, flag))
        self._changed()
        return self.find_event(event_id)

    def update_event(self, event_id: str, title: str, starts_at: datetime, ends_at: datetime, *,
                     all_day: bool = False, notes: str = "", recurrence: str = "none",
                     flag: str = "none") -> Event:
        title, notes = _text(title, notes)
        starts, ends = _span(starts_at, ends_at, all_day)
        recurrence, flag = _recurrence(recurrence, all_day), _flag(flag)
        with self.event_db.connect(write=True) as db:
            updated = db.execute("""UPDATE events SET title=?,notes=?,starts_at=?,ends_at=?,all_day=?,
                recurrence=?,flag=? WHERE id=?""",
                                 (title, notes, starts, ends, int(all_day), recurrence, flag,
                                  event_id)).rowcount
        if not updated:
            raise ValueError("The event no longer exists")
        self._changed()
        return self.find_event(event_id)

    def delete_event(self, event_id: str) -> bool:
        with self.event_db.connect(write=True) as db:
            deleted = db.execute("DELETE FROM events WHERE id=?", (event_id,)).rowcount == 1
        if deleted:
            self._changed()
        return deleted

    def find_event(self, event_id: str) -> Event | None:
        with self.event_db.connect() as db:
            row = db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        return Event.from_row(row) if row else None

    def events(self, first: date | None = None, last: date | None = None) -> list[Event]:
        """Events touching any day from first to last, both inclusive, with repeating events
        expanded into each repetition when both days are given."""
        clauses, values = [], []
        if last is not None:
            clauses.append("starts_at < ?")
            values.append(to_local(day_start(last + timedelta(days=1))))
        if first is not None:
            clauses.append("(ends_at >= ? OR recurrence <> 'none')")
            values.append(to_local(day_start(first)))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.event_db.connect() as db:
            rows = db.execute(f"SELECT * FROM events{where} ORDER BY starts_at,ends_at,id", values)
            events = [Event.from_row(row) for row in rows]
        if first is not None and last is not None:
            events = sorted((occurrence for event in events for occurrence in event.occurrences(first, last)),
                            key=lambda event: (event.starts_at, event.ends_at, event.id))
        return [event for event in events if first is None or event.is_recurring or event.last_day >= first]

    def search(self, query: str, limit: int = 100) -> list[Entry]:
        """Reminders and events whose title or notes contain every word of query, ignoring case."""
        words = str(query).casefold().split()
        if not words:
            return []
        with self.reminder_db.connect() as db:
            reminders = [Reminder.from_row(row) for row in db.execute("SELECT * FROM reminders")]
        found = [entry for entry in [*reminders, *self.events()]
                 if all(word in f"{entry.title}\n{entry.notes}".casefold() for word in words)]
        found.sort(key=lambda entry: entry.moment, reverse=True)
        return found[:limit]

    def entries(self, first: date, last: date) -> list[Entry]:
        """Reminders and events touching any day from first to last, in chronological order."""
        reminders = self.reminders(day_start(first), day_start(last + timedelta(days=1)))
        entries = [*self.events(first, last), *reminders]
        return sorted(entries, key=lambda entry: (entry.moment, isinstance(entry, Reminder),
                                                  entry.title.casefold()))

    def busy_days(self, first: date, last: date) -> dict[date, int]:
        """Number of entries on each day from first to last that has at least one."""
        counts: dict[date, int] = {}
        for entry in self.entries(first, last):
            for day in entry.days():
                if first <= day <= last:
                    counts[day] = counts.get(day, 0) + 1
        return counts
