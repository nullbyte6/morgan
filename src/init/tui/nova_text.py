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
"""Nova's dates, times and Markdown in the terminal, following the desktop's patterns without Qt."""
import re
from datetime import date, datetime, timedelta

from src.init.nova.entries import Entry, Reminder
from src.init.tui import i18n
from src.init.tui.i18n import t

NAMES = {
    "english": {
        "days": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
        "short_days": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
        "months": ("January", "February", "March", "April", "May", "June", "July", "August", "September",
                   "October", "November", "December"),
        "short_months": ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
    },
    "spanish": {
        "days": ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"),
        "short_days": ("lun", "mar", "mié", "jue", "vie", "sáb", "dom"),
        "months": ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
                   "octubre", "noviembre", "diciembre"),
        "short_months": ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sept", "oct", "nov", "dic"),
    },
    "chinese": {
        "days": ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"),
        "short_days": ("周一", "周二", "周三", "周四", "周五", "周六", "周日"),
        "months": ("一月", "二月", "三月", "四月", "五月", "六月", "七月", "八月", "九月", "十月", "十一月",
                   "十二月"),
        "short_months": tuple(f"{month}月" for month in range(1, 13)),
    },
}
TOKEN = re.compile(r"'[^']*'|d{1,4}|M{1,4}|y{4}|y{2}")
REPEAT = "↻"
FLAG = "⚑"
PENCIL = "✎"


def names() -> dict:
    return NAMES.get(i18n.language(), NAMES["english"])


def capitalized(text: str) -> str:
    return text[:1].upper() + text[1:]


def weekday_name(index: int, style: str = "short") -> str:
    return capitalized(names()["short_days" if style == "short" else "days"][index])


def format_day(day: date, pattern_key: str) -> str:
    """The day written with one of the desktop's date patterns, such as dddd, d MMMM."""
    table = names()

    def token(match) -> str:
        text = match.group()
        if text.startswith("'"):
            return text[1:-1]
        values = {"d": str(day.day), "dd": f"{day.day:02d}", "ddd": table["short_days"][day.weekday()],
                  "dddd": table["days"][day.weekday()], "M": str(day.month), "MM": f"{day.month:02d}",
                  "MMM": table["short_months"][day.month - 1], "MMMM": table["months"][day.month - 1],
                  "yy": f"{day.year % 100:02d}", "yyyy": str(day.year)}
        return values[text]

    return capitalized(TOKEN.sub(token, t(pattern_key)))


def time_text(moment: datetime) -> str:
    return f"{moment:%H:%M}"


def date_time_text(moment: datetime) -> str:
    return f"{format_day(moment.date(), 'nova.format.short_day')}, {time_text(moment)}"


def day_heading(day: date, today: date | None = None) -> str:
    today = today or date.today()
    known = {today: "nova.today", today + timedelta(days=1): "nova.tomorrow",
             today - timedelta(days=1): "nova.yesterday"}
    heading = format_day(day, "nova.format.day")
    return f"{t(known[day])} · {heading}" if day in known else heading


def month_title(day: date) -> str:
    return format_day(day, "nova.format.month")


def week_title(first: date, last: date) -> str:
    return f"{format_day(first, 'nova.format.range_day')} – {format_day(last, 'nova.format.range_day')} {last.year}"


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def event_time_text(event) -> str:
    """The time span of an event: all day, a clock range, or both ends when it spans days."""
    if event.all_day:
        if event.first_day == event.last_day:
            return t("nova.all_day")
        return (f"{format_day(event.first_day, 'nova.format.short_day')} – "
                f"{format_day(event.last_day, 'nova.format.short_day')}")
    if event.starts_at.date() == event.ends_at.date():
        return f"{time_text(event.starts_at)} – {time_text(event.ends_at)}"
    return f"{date_time_text(event.starts_at)} – {date_time_text(event.ends_at)}"


def entry_when(entry: Entry, today: date) -> str:
    """When an entry happens, with the day only when it is not today."""
    if isinstance(entry, Reminder):
        moment = entry.remind_at
        return time_text(moment) if moment.date() == today else date_time_text(moment)
    if entry.first_day == entry.last_day and entry.first_day != today:
        return f"{format_day(entry.first_day, 'nova.format.short_day')}, {event_time_text(entry)}"
    return event_time_text(entry)


def entry_markdown(entry: Entry) -> str:
    if isinstance(entry, Reminder):
        mark = "[x]" if entry.is_completed else "[ ]"
        line = f"- {mark} {time_text(entry.remind_at)} {entry.title}"
    else:
        line = f"- {event_time_text(entry)} {entry.title}"
    notes = "\n".join(f"  {text}" for text in entry.notes.splitlines() if text.strip())
    return f"{line}\n{notes}" if notes else line


def day_markdown(day: date, entries: list, memories: list[dict], conversations: list[tuple[dict, list]]) -> str:
    """One diary day as Markdown: the agenda, what was remembered and every message of each conversation."""
    from src.init.nova.journal import clipped
    parts = [f"# {day_heading(day)}"]
    if entries:
        parts.append(f"## {t('nova.diary.agenda')}\n\n" + "\n".join(entry_markdown(entry) for entry in entries))
    if memories:
        parts.append(f"## {t('nova.diary.learned')}\n\n"
                     + "\n".join(f"- {' '.join(memory['content'].split())}" for memory in memories))
    if conversations:
        parts.append(f"## {t('nova.diary.conversations')}")
        for session, messages in conversations:
            topic = clipped(session["topic"]) or t("nova.diary.untitled")
            parts.append(f"### {time_text(session['started'])} · {topic}")
            parts.extend(f"**{author}** · {stamp}\n\n{content}" for author, stamp, content in messages)
    return "\n\n".join(parts) + "\n"
