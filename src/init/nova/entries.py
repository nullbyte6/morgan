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
"""Reminders and events as immutable records with local wall-clock times."""
from __future__ import annotations

import re
from calendar import monthrange
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from functools import lru_cache

LOCAL_FORMAT = "%Y-%m-%dT%H:%M"
TITLE_LIMIT = 200
NOTES_LIMIT = 4000
JOURNAL_LIMIT = 20000
JOURNAL_AUTHORS = ("user", "assistant")
MAX_SPAN_DAYS = 366
MAX_OCCURRENCES = 2000
MAX_REPEAT_COUNT = 999
RECURRENCES = ("none", "daily", "weekly", "monthly")
REPEAT_UNITS = ("hours", "days", "weeks", "months", "years")
FLAGS = ("none", "green", "yellow", "red")
FLAG_ROLES = {"green": "success", "yellow": "warning", "red": "error"}
FLAG_COUNTS = {"green": 1, "yellow": 2, "red": 3}
FLAG_RANKS = {"red": 0, "yellow": 1, "green": 2, "none": 3}
STEP_DELTAS = {"hours": timedelta(hours=1), "days": timedelta(days=1), "weeks": timedelta(weeks=1)}
STEP_MONTHS = {"months": 1, "years": 12}
SINGLE_NAMES = {"hours": "hourly", "days": "daily", "weeks": "weekly", "months": "monthly", "years": "yearly"}
ALIASES = {"hourly": (1, "hours"), "daily": (1, "days"), "weekly": (1, "weeks"), "monthly": (1, "months"),
           "yearly": (1, "years")}
REPEAT_TEXT = re.compile(r"(?:every\s+)?(?:(\d+)\s*:?\s*)?(hour|day|week|month|year)s?")


def to_local(moment: datetime) -> str:
    """Store a moment as minute-precision wall-clock text, ignoring any timezone."""
    return moment.replace(second=0, microsecond=0, tzinfo=None).strftime(LOCAL_FORMAT)


def from_local(value: str) -> datetime:
    return datetime.strptime(value, LOCAL_FORMAT)


def day_start(day: date) -> datetime:
    return datetime.combine(day, time.min)


def flagged_first(entries) -> list:
    """The entries with red flags first, then yellow, green and unflagged, each keeping its order."""
    return sorted(entries, key=lambda entry: FLAG_RANKS[entry.flag])


@lru_cache(maxsize=64)
def parse_recurrence(value: str) -> tuple[int, str] | None:
    """The repeat as (interval, unit) such as (2, "weeks"), or None for none. Accepts none, daily,
    weekly, monthly, hourly, yearly, "every 3 days" and the stored form "3:days"."""
    text = str(value or "none").strip().casefold()
    if text == "none":
        return None
    if text in ALIASES:
        return ALIASES[text]
    match = REPEAT_TEXT.fullmatch(text)
    if match is None:
        raise ValueError("The repetition must be none, daily, weekly, monthly or every N hours, days, "
                         "weeks, months or years")
    count = int(match[1] or 1)
    if not 1 <= count <= MAX_REPEAT_COUNT:
        raise ValueError(f"The repetition interval must be between 1 and {MAX_REPEAT_COUNT}")
    return count, match[2] + "s"


def normalize_recurrence(value: str) -> str:
    """The stored form of a repeat: none, daily, weekly or monthly, else interval and unit as "3:days"."""
    parsed = parse_recurrence(value)
    if parsed is None:
        return "none"
    count, unit = parsed
    if count == 1 and unit in ("days", "weeks", "months"):
        return SINGLE_NAMES[unit]
    return f"{count}:{unit}"


def recurrence_label(recurrence: str, translate) -> str:
    """The repeat in words through translate, e.g. "Daily" or "Every 2 weeks"."""
    parsed = parse_recurrence(recurrence)
    if parsed is None:
        return translate("nova.repeat.none")
    count, unit = parsed
    if count == 1:
        return translate(f"nova.repeat.{SINGLE_NAMES[unit]}")
    return translate(f"nova.repeat.every_{unit}", count=count)


def shift(moment: datetime, recurrence: str, count: int) -> datetime:
    """The moment count repetitions later, keeping the day of the month where the month allows it."""
    parsed = parse_recurrence(recurrence)
    if parsed is None:
        return moment
    every, unit = parsed
    if unit in STEP_DELTAS:
        return moment + STEP_DELTAS[unit] * (every * count)
    months = moment.month - 1 + STEP_MONTHS[unit] * every * count
    year, month = moment.year + months // 12, months % 12 + 1
    return moment.replace(year=year, month=month, day=min(moment.day, monthrange(year, month)[1]))


def steps_before(moment: datetime, recurrence: str, target: datetime) -> int:
    """A number of repetitions that never takes moment past target."""
    parsed = parse_recurrence(recurrence)
    if target <= moment or parsed is None:
        return 0
    every, unit = parsed
    if unit in STEP_DELTAS:
        return (target - moment) // (STEP_DELTAS[unit] * every)
    months = (target.year - moment.year) * 12 + target.month - moment.month - 1
    return max(0, months // (STEP_MONTHS[unit] * every))


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
    flag: str = "none"

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
                   row["created_at"], row["completed_at"], row["notified_at"], row["recurrence"],
                   row["flag"])


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
    flag: str = "none"

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

    def _walk(self, first: date, last: date):
        span = self.ends_at - self.starts_at
        reach = (self.last_day - self.first_day).days + 1
        count = steps_before(self.starts_at, self.recurrence, day_start(first - timedelta(days=reach)))
        for count in range(count, count + MAX_OCCURRENCES):
            starts_at = shift(self.starts_at, self.recurrence, count)
            if starts_at.date() > last:
                break
            occurrence = replace(self, starts_at=starts_at, ends_at=starts_at + span)
            if occurrence.last_day >= first:
                yield occurrence

    def occurrences(self, first: date, last: date) -> list[Event]:
        """The repetitions of this event touching any day from first to last, both inclusive."""
        if not self.is_recurring:
            return [self] if self.first_day <= last and self.last_day >= first else []
        return list(self._walk(first, last))

    def next_from(self, day: date) -> Event:
        """This event, or its first repetition that has not ended before day."""
        if not self.is_recurring or self.last_day >= day:
            return self
        return next(self._walk(day, day + timedelta(days=MAX_SPAN_DAYS * 2)), self)

    @classmethod
    def from_row(cls, row) -> Event:
        return cls(row["id"], row["title"], row["notes"], from_local(row["starts_at"]),
                   from_local(row["ends_at"]), bool(row["all_day"]), row["created_at"], row["recurrence"],
                   row["flag"])


Entry = Reminder | Event


@dataclass(frozen=True, slots=True)
class JournalEntry:
    id: str
    day: date
    text: str
    author: str
    created_at: str
    modified_at: str

    @property
    def is_edited(self) -> bool:
        return self.modified_at != self.created_at

    @classmethod
    def from_row(cls, row) -> JournalEntry:
        return cls(row["id"], date.fromisoformat(row["day"]), row["body"], row["author"],
                   row["created_at"], row["modified_at"])
