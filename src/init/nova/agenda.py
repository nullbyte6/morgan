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
"""How the agenda, reminder and event lists group what the store holds."""
from datetime import datetime, timedelta

from src.init.lang import tr

from . import formatting
from .entries import Entry, day_start
from .store import NovaStore

AGENDA_DAYS = 14
HISTORY_LIMIT = 50

Groups = list[tuple[str, list[Entry]]]


def agenda_groups(store: NovaStore, now: datetime) -> Groups:
    """Overdue reminders, then each of the next days that has something on it."""
    today = now.date()
    groups: Groups = [(tr("nova.group.overdue"), list(store.reminders(end=day_start(today), completed=False)))]
    last = today + timedelta(days=AGENDA_DAYS - 1)
    by_day: dict = {}
    for entry in store.entries(today, last):
        for day in entry.days():
            if today <= day <= last:
                by_day.setdefault(day, []).append(entry)
    groups.extend((formatting.day_heading(day, today), by_day[day]) for day in sorted(by_day))
    return groups


def reminder_groups(store: NovaStore) -> Groups:
    completed = store.reminders(completed=True)[::-1][:HISTORY_LIMIT]
    return [(tr("nova.group.pending"), store.reminders(completed=False)),
            (tr("nova.group.completed"), completed)]


def event_groups(store: NovaStore, now: datetime) -> Groups:
    today = now.date()
    events = [event.next_from(today) for event in store.events()]
    upcoming = sorted((event for event in events if event.last_day >= today),
                      key=lambda event: (event.starts_at, event.ends_at, event.id))
    past = [event for event in events if event.last_day < today][::-1][:HISTORY_LIMIT]
    return [(tr("nova.group.upcoming"), upcoming), (tr("nova.group.past"), past)]
