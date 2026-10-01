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
"""Dates, times and day names rendered in Arlo's interface language."""
from datetime import date, datetime, timedelta
from functools import lru_cache
from time import monotonic

from PySide6.QtCore import QDate, QLocale, QTime

from src.init.lang import get_language, tr

LOCALES = {"english": "en_GB", "spanish": "es_ES", "chinese": "zh_CN"}
NAME_STYLES = {"long": QLocale.FormatType.LongFormat, "short": QLocale.FormatType.ShortFormat,
               "narrow": QLocale.FormatType.NarrowFormat}


@lru_cache(maxsize=4)
def _locale(name: str) -> QLocale:
    return QLocale(name)


_language = ("", float("-inf"))


def locale() -> QLocale:
    """The locale of the interface language, re-read from the settings twice a second at most."""
    global _language
    name, read_at = _language
    if monotonic() - read_at > 0.5:
        name = get_language()
        _language = (name, monotonic())
    return _locale(LOCALES.get(name, "en_GB"))


def capitalized(text: str) -> str:
    return text[:1].upper() + text[1:]


def first_weekday() -> int:
    """The first day of the week in the interface language, counting from Monday as 0."""
    return int(locale().firstDayOfWeek().value) - 1


def weekday_name(index: int, style: str = "short") -> str:
    return capitalized(locale().dayName(index + 1, NAME_STYLES[style]).rstrip("."))


def month_name(month: int, style: str = "long") -> str:
    return capitalized(locale().monthName(month, NAME_STYLES[style]).rstrip("."))


def qdate(day: date) -> QDate:
    return QDate(day.year, day.month, day.day)


def format_day(day: date, pattern_key: str) -> str:
    return capitalized(locale().toString(qdate(day), tr(pattern_key)))


def time_text(moment: datetime) -> str:
    return locale().toString(QTime(moment.hour, moment.minute), QLocale.FormatType.ShortFormat)


def date_time_text(moment: datetime) -> str:
    return f"{format_day(moment.date(), 'nova.format.short_day')}, {time_text(moment)}"


def day_heading(day: date, today: date | None = None) -> str:
    today = today or date.today()
    names = {today: "nova.today", today + timedelta(days=1): "nova.tomorrow",
             today - timedelta(days=1): "nova.yesterday"}
    heading = format_day(day, "nova.format.day")
    return f"{tr(names[day])} · {heading}" if day in names else heading


def month_title(day: date) -> str:
    return format_day(day, "nova.format.month")


def week_title(first: date, last: date) -> str:
    start = format_day(first, "nova.format.range_day")
    return f"{start} – {format_day(last, 'nova.format.range_day')} {last.year}"


def event_time_text(event) -> str:
    """The time span of an event: all day, a clock range, or both ends when it spans days."""
    if event.all_day:
        if event.first_day == event.last_day:
            return tr("nova.all_day")
        return f"{format_day(event.first_day, 'nova.format.short_day')} – {format_day(event.last_day, 'nova.format.short_day')}"
    if event.starts_at.date() == event.ends_at.date():
        return f"{time_text(event.starts_at)} – {time_text(event.ends_at)}"
    return f"{date_time_text(event.starts_at)} – {date_time_text(event.ends_at)}"
