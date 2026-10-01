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
"""Reminders and events as immutable records with local wall-clock times."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

LOCAL_FORMAT = "%Y-%m-%dT%H:%M"
TITLE_LIMIT = 200
NOTES_LIMIT = 4000
MAX_SPAN_DAYS = 366


def to_local(moment: datetime) -> str:
    """Store a moment as minute-precision wall-clock text, ignoring any timezone."""
    return moment.replace(second=0, microsecond=0, tzinfo=None).strftime(LOCAL_FORMAT)


def from_local(value: str) -> datetime:
    return datetime.strptime(value, LOCAL_FORMAT)


def day_start(day: date) -> datetime:
    return datetime.combine(day, time.min)


@dataclass(frozen=True, slots=True)
class Reminder:
    id: str
    title: str
    notes: str
    remind_at: datetime
    created_at: str
    completed_at: str | None = None
    notified_at: str | None = None

    @property
    def is_completed(self) -> bool:
        return self.completed_at is not None

    @property
    def moment(self) -> datetime:
        return self.remind_at

    @property
    def first_day(self) -> date:
        return self.remind_at.date()

    @property
    def last_day(self) -> date:
        return self.remind_at.date()

    def days(self) -> list[date]:
        return [self.remind_at.date()]

    @classmethod
    def from_row(cls, row) -> Reminder:
        return cls(row["id"], row["title"], row["notes"], from_local(row["remind_at"]),
                   row["created_at"], row["completed_at"], row["notified_at"])


@dataclass(frozen=True, slots=True)
class Event:
    id: str
    title: str
    notes: str
    starts_at: datetime
    ends_at: datetime
    all_day: bool
    created_at: str

    @property
    def moment(self) -> datetime:
        return self.starts_at

    @property
    def first_day(self) -> date:
        return self.starts_at.date()

    @property
    def last_day(self) -> date:
        if self.ends_at > self.starts_at and self.ends_at.time() == time.min:
            return (self.ends_at - timedelta(days=1)).date()
        return self.ends_at.date()

    def spans(self, day: date) -> bool:
        return self.first_day <= day <= self.last_day

    def days(self) -> list[date]:
        count = min((self.last_day - self.first_day).days + 1, MAX_SPAN_DAYS)
        return [self.first_day + timedelta(days=offset) for offset in range(count)]

    @classmethod
    def from_row(cls, row) -> Event:
        return cls(row["id"], row["title"], row["notes"], from_local(row["starts_at"]),
                   from_local(row["ends_at"]), bool(row["all_day"]), row["created_at"])


Entry = Reminder | Event
