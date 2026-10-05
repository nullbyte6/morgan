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
"""The three SQLite databases behind Nova: one for reminders, one for events and one for the journal."""
from src.init.memory.database import Database

LOCAL_TIME = "'[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]'"
RECURRENCE = "recurrence TEXT NOT NULL DEFAULT 'none' CHECK(recurrence IN ('none','daily','weekly','monthly'))"
REPEATING = "recurrence TEXT NOT NULL DEFAULT 'none' CHECK(recurrence IN ('none','daily','weekly','monthly') OR recurrence GLOB '[1-9]*:[a-z]*')"
FLAG = "flag TEXT NOT NULL DEFAULT 'none' CHECK(flag IN ('none','green','yellow','red'))"

REMINDER_MIGRATIONS = (
    (
        f"""CREATE TABLE reminders (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 200),
            notes TEXT NOT NULL DEFAULT '' CHECK(length(notes) <= 4000),
            remind_at TEXT NOT NULL CHECK(remind_at GLOB {LOCAL_TIME}),
            created_at TEXT NOT NULL, completed_at TEXT, notified_at TEXT)""",
        "CREATE INDEX reminders_time ON reminders(remind_at)",
        "CREATE INDEX reminders_pending ON reminders(completed_at, notified_at, remind_at)",
    ),
    (f"ALTER TABLE reminders ADD COLUMN {RECURRENCE}",),
    (f"ALTER TABLE reminders ADD COLUMN {FLAG}",),
    (
        f"""CREATE TABLE reminders_new (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 200),
            notes TEXT NOT NULL DEFAULT '' CHECK(length(notes) <= 4000),
            remind_at TEXT NOT NULL CHECK(remind_at GLOB {LOCAL_TIME}),
            created_at TEXT NOT NULL, completed_at TEXT, notified_at TEXT,
            {REPEATING}, {FLAG})""",
        """INSERT INTO reminders_new(id,title,notes,remind_at,created_at,completed_at,notified_at,recurrence,flag)
            SELECT id,title,notes,remind_at,created_at,completed_at,notified_at,recurrence,flag FROM reminders""",
        "DROP TABLE reminders",
        "ALTER TABLE reminders_new RENAME TO reminders",
        "CREATE INDEX reminders_time ON reminders(remind_at)",
        "CREATE INDEX reminders_pending ON reminders(completed_at, notified_at, remind_at)",
    ),
)

EVENT_MIGRATIONS = (
    (
        f"""CREATE TABLE events (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 200),
            notes TEXT NOT NULL DEFAULT '' CHECK(length(notes) <= 4000),
            starts_at TEXT NOT NULL CHECK(starts_at GLOB {LOCAL_TIME}),
            ends_at TEXT NOT NULL CHECK(ends_at GLOB {LOCAL_TIME}),
            all_day INTEGER NOT NULL DEFAULT 0 CHECK(all_day IN (0, 1)),
            created_at TEXT NOT NULL, CHECK(ends_at >= starts_at))""",
        "CREATE INDEX events_time ON events(starts_at, ends_at)",
    ),
    (f"ALTER TABLE events ADD COLUMN {RECURRENCE}",),
    (f"ALTER TABLE events ADD COLUMN {FLAG}",),
    (
        f"""CREATE TABLE events_new (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 200),
            notes TEXT NOT NULL DEFAULT '' CHECK(length(notes) <= 4000),
            starts_at TEXT NOT NULL CHECK(starts_at GLOB {LOCAL_TIME}),
            ends_at TEXT NOT NULL CHECK(ends_at GLOB {LOCAL_TIME}),
            all_day INTEGER NOT NULL DEFAULT 0 CHECK(all_day IN (0, 1)),
            created_at TEXT NOT NULL, {REPEATING}, {FLAG}, CHECK(ends_at >= starts_at))""",
        """INSERT INTO events_new(id,title,notes,starts_at,ends_at,all_day,created_at,recurrence,flag)
            SELECT id,title,notes,starts_at,ends_at,all_day,created_at,recurrence,flag FROM events""",
        "DROP TABLE events",
        "ALTER TABLE events_new RENAME TO events",
        "CREATE INDEX events_time ON events(starts_at, ends_at)",
    ),
)

JOURNAL_MIGRATIONS = (
    (
        """CREATE TABLE journal (
            id TEXT PRIMARY KEY,
            day TEXT NOT NULL CHECK(day GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
            body TEXT NOT NULL CHECK(length(body) BETWEEN 1 AND 20000),
            author TEXT NOT NULL DEFAULT 'user' CHECK(author IN ('user','assistant')),
            created_at TEXT NOT NULL, modified_at TEXT NOT NULL)""",
        "CREATE INDEX journal_day ON journal(day, created_at)",
    ),
)


class ReminderDatabase(Database):
    migrations = REMINDER_MIGRATIONS


class EventDatabase(Database):
    migrations = EVENT_MIGRATIONS


class JournalDatabase(Database):
    migrations = JOURNAL_MIGRATIONS
