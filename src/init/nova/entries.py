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

from calendar import monthrange
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta

LOCAL_FORMAT = "%Y-%m-%dT%H:%M"
TITLE_LIMIT = 200
NOTES_LIMIT = 4000
MAX_SPAN_DAYS = 366
RECURRENCES = ("none", "daily", "weekly", "monthly")
STEP_DAYS = {"daily": 1, "weekly": 7}


def to_local(moment: datetime) -> str:
    """Store a moment as minute-precision wall-clock text, ignoring any timezone."""
    return moment.replace(second=0, microsecond=0, tzinfo=None).strftime(LOCAL_FORMAT)


def from_local(value: str) -> datetime:
    return datetime.strptime(value, LOCAL_FORMAT)


def day_start(day: date) -> datetime:
    return datetime.combine(day, time.min)


def shift(moment: datetime, recurrence: str, count: int) -> datetime:
    """The moment count repetitions later, keeping the day of the month where the month allows it."""
    if recurrence in STEP_DAYS:
        return moment + timedelta(days=STEP_DAYS[recurrence] * count)
    if recurrence == "monthly":
        months = moment.month - 1 + count
        year, month = moment.year + months // 12, months % 12 + 1
        return moment.replace(year=year, month=month, day=min(moment.day, monthrange(year, month)[1]))
    return moment


def steps_before(moment: datetime, recurrence: str, target: datetime) -> int:
    """A number of repetitions that never takes moment past target."""
    if target <= moment:
        return 0
    if recurrence in STEP_DAYS:
        return (target - moment).days // STEP_DAYS[recurrence]
    if recurrence == "monthly":
        return max(0, (target.year - moment.year) * 12 + target.month - moment.month - 1)
    return 0


def next_occurrence(moment: datetime, recurrence: str, after: datetime) -> datetime:
    """The first repetition of moment that falls strictly after after."""
    count = max(1, steps_before(moment, recurrence, after))
    while shift(moment, recurrence, count) <= after:
        count += 1
    return shift(moment, recurrence, count)


@dataclass(frozen=True, slots=True)
class Reminder:
    id: str
    title: str
    notes: str
    remind_at: datetime
    created_at: str
    completed_at: str | None = None
    notified_at: str | None = None
    recurrence: str = "none"

    @property
    def is_recurring(self) -> bool:
        return self.recurrence != "none"

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
                   row["created_at"], row["completed_at"], row["notified_at"], row["recurrence"])


@dataclass(frozen=True, slots=True)
class Event:
    id: str
    title: str
    notes: str
    starts_at: datetime
    ends_at: datetime
    all_day: bool
    created_at: str
    recurrence: str = "none"

    @property
    def is_recurring(self) -> bool:
        return self.recurrence != "none"

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

    def occurrences(self, first: date, last: date) -> list[Event]:
        """The repetitions of this event touching any day from first to last, both inclusive."""
        if not self.is_recurring:
            return [self] if self.first_day <= last and self.last_day >= first else []
        span = self.ends_at - self.starts_at
        reach = (self.last_day - self.first_day).days + 1
        count = steps_before(self.starts_at, self.recurrence, day_start(first - timedelta(days=reach)))
        found = []
        for count in range(count, count + MAX_SPAN_DAYS * 2):
            starts_at = shift(self.starts_at, self.recurrence, count)
            if starts_at.date() > last:
                break
            occurrence = replace(self, starts_at=starts_at, ends_at=starts_at + span)
            if occurrence.last_day >= first:
                found.append(occurrence)
        return found

    def next_from(self, day: date) -> Event:
        """This event, or its first repetition that has not ended before day."""
        if not self.is_recurring or self.last_day >= day:
            return self
        return next(iter(self.occurrences(day, day + timedelta(days=MAX_SPAN_DAYS * 2))), self)

    @classmethod
    def from_row(cls, row) -> Event:
        return cls(row["id"], row["title"], row["notes"], from_local(row["starts_at"]),
                   from_local(row["ends_at"]), bool(row["all_day"]), row["created_at"], row["recurrence"])


Entry = Reminder | Event
