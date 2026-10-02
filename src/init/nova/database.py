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
"""The two SQLite databases behind Nova: one for reminders and one for events."""
from src.init.memory.database import Database

LOCAL_TIME = "'[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]'"
RECURRENCE = "recurrence TEXT NOT NULL DEFAULT 'none' CHECK(recurrence IN ('none','daily','weekly','monthly'))"

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
)


class ReminderDatabase(Database):
    migrations = REMINDER_MIGRATIONS


class EventDatabase(Database):
    migrations = EVENT_MIGRATIONS
