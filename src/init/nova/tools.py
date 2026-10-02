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
"""Assistant tools that read and write Nova's reminders and events."""
from __future__ import annotations

import threading
from datetime import date, datetime, timedelta

_lock = threading.Lock()
_store = None


def use_store(store) -> None:
    global _store
    with _lock:
        _store = store


def _shared():
    global _store
    with _lock:
        if _store is None:
            try:
                from .store import NovaStore
            except ImportError as error:
                raise ValueError("Nova is only available in the desktop version") from error
            _store = NovaStore()
        return _store


def refresh_store() -> None:
    """Tell the views of the shared store that its databases were replaced underneath them."""
    with _lock:
        store = _store
    if store is not None:
        store.changed.emit()


def _moment(value: str, name: str) -> datetime:
    try:
        moment = datetime.fromisoformat(str(value).strip())
    except ValueError as error:
        raise ValueError(f"{name} must be a local ISO date and time such as 2026-10-02T09:30") from error
    if moment.tzinfo is not None:
        moment = moment.astimezone().replace(tzinfo=None)
    return moment


def _day(value: str, name: str) -> date:
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError as error:
        raise ValueError(f"{name} must be an ISO date such as 2026-10-02") from error


def _reminder(reminder) -> dict:
    return {"id": reminder.id, "kind": "reminder", "title": reminder.title, "notes": reminder.notes,
            "remind_at": reminder.remind_at.isoformat(timespec="minutes"),
            "completed": reminder.is_completed, "repeat": reminder.recurrence}


def _event(event) -> dict:
    return {"id": event.id, "kind": "event", "title": event.title, "notes": event.notes,
            "starts_at": event.starts_at.isoformat(timespec="minutes"),
            "ends_at": event.ends_at.isoformat(timespec="minutes"), "all_day": event.all_day,
            "repeat": event.recurrence}


def _entry(entry) -> dict:
    return _event(entry) if hasattr(entry, "starts_at") else _reminder(entry)


def add_reminder(title: str, remind_at: str, notes: str = "", repeat: str = "none") -> dict:
    """Save a reminder in Nova, the user's agenda, announced as a Windows notification when due.
    remind_at is local wall-clock time as ISO, e.g. 2026-10-02T09:30; check get_current_time
    for relative requests. Persists across restarts. Prefer this over schedule_notification
    for anything the user asks to be reminded of at a date or time.
    repeat is none, daily, weekly or monthly; a repeating reminder comes back at the same time.
    """
    try:
        moment = _moment(remind_at, "remind_at")
        if moment < datetime.now() - timedelta(minutes=1):
            raise ValueError("remind_at is in the past")
        return {"ok": True, "reminder": _reminder(_shared().add_reminder(title, moment, notes, repeat))}
    except Exception as error:
        return {"ok": False, "error": str(error)}


def add_event(title: str, starts_at: str, ends_at: str | None = None,
              all_day: bool = False, notes: str = "", repeat: str = "none") -> dict:
    """Save an event in Nova's calendar. Times are local ISO, e.g. 2026-10-02T18:00.
    ends_at defaults to one hour after starts_at, or the same day when all_day.
    repeat is none, daily, weekly or monthly for events that happen again, e.g. a weekly class.
    """
    try:
        starts = _moment(starts_at, "starts_at")
        if ends_at:
            ends = _moment(ends_at, "ends_at")
        else:
            ends = starts if all_day else starts + timedelta(hours=1)
        return {"ok": True, "event": _event(_shared().add_event(title, starts, ends, all_day=all_day,
                                                               notes=notes, recurrence=repeat))}
    except Exception as error:
        return {"ok": False, "error": str(error)}


def list_agenda(first_day: str | None = None, last_day: str | None = None) -> dict:
    """List Nova reminders and events from first_day to last_day, both inclusive ISO dates.
    Defaults to today and the next 13 days. Pending overdue reminders are always included.
    """
    try:
        first = _day(first_day, "first_day") if first_day else date.today()
        last = _day(last_day, "last_day") if last_day else first + timedelta(days=13)
        if last < first:
            raise ValueError("last_day cannot be before first_day")
        if (last - first).days > 366:
            raise ValueError("The range cannot exceed 366 days")
        store = _shared()
        overdue = [reminder for reminder in store.overdue() if reminder.remind_at.date() < first]
        return {"ok": True, "first_day": first.isoformat(), "last_day": last.isoformat(),
                "overdue": [_reminder(reminder) for reminder in overdue],
                "entries": [_entry(entry) for entry in store.entries(first, last)]}
    except Exception as error:
        return {"ok": False, "error": str(error)}


def search_agenda(query: str, limit: int = 20) -> dict:
    """Find Nova reminders and events, past or upcoming and done or pending, whose title or notes
    contain every word of query, newest first. Use it to find an entry by name when its date is
    unknown, e.g. before update_agenda_entry or delete_agenda_entry. Use recall for conversations.
    """
    try:
        if not str(query).split():
            raise ValueError("query must contain at least one word")
        limit = min(max(1, int(limit)), 100)
        found = _shared().search(query, limit=limit)
        return {"ok": True, "query": query, "entries": [_entry(entry) for entry in found]}
    except Exception as error:
        return {"ok": False, "error": str(error)}


def agenda_brief(now: datetime | None = None, limit: int = 8) -> str:
    """Today's pending reminders and events and the number of overdue reminders, in a few words."""
    now = now or datetime.now()
    today = now.date()
    store = _shared()
    parts = []
    for entry in store.entries(today, today):
        if hasattr(entry, "starts_at"):
            if entry.all_day:
                when = "all day"
            elif entry.starts_at.date() == today:
                when = f"{entry.starts_at:%H:%M}"
            else:
                when = f"until {entry.ends_at:%H:%M}" if entry.ends_at.date() == today else "all day"
            parts.append(f"event {entry.title} ({when})")
        elif not entry.is_completed:
            parts.append(f"reminder {entry.title} ({entry.remind_at:%H:%M})")
    overdue = sum(1 for reminder in store.overdue(now) if reminder.remind_at.date() < today)
    if overdue:
        parts.append(f"{overdue} overdue reminder{'s' if overdue > 1 else ''} from earlier days")
    if len(parts) > limit:
        parts = parts[:limit] + [f"{len(parts) - limit} more"]
    return "; ".join(parts)


def complete_reminder(reminder_id: str, completed: bool = True) -> dict:
    """Mark a Nova reminder as done, or pending again with completed false. Use IDs from list_agenda.
    Completing a repeating reminder moves it to its next time."""
    try:
        return {"ok": True, "reminder": _reminder(_shared().set_reminder_completed(reminder_id, completed))}
    except Exception as error:
        return {"ok": False, "error": str(error)}


def update_agenda_entry(entry_id: str, title: str | None = None, remind_at: str | None = None,
                        starts_at: str | None = None, ends_at: str | None = None,
                        all_day: bool | None = None, notes: str | None = None,
                        repeat: str | None = None) -> dict:
    """Change or reschedule one Nova reminder or event by exact ID from list_agenda, keeping its ID.
    Pass only the fields to change; times are local ISO, e.g. 2026-10-02T17:00.
    remind_at applies to reminders; starts_at, ends_at and all_day to events. Moving an event's
    start without ends_at keeps its duration. Changing a repeating entry changes the whole series.
    repeat is none, daily, weekly or monthly.
    """
    try:
        store = _shared()
        reminder = store.reminder(entry_id)
        if reminder is not None:
            if starts_at or ends_at or all_day is not None:
                raise ValueError("Reminders only take remind_at; starts_at, ends_at and all_day are for events")
            moment = _moment(remind_at, "remind_at") if remind_at else reminder.remind_at
            return {"ok": True, "reminder": _reminder(store.update_reminder(
                entry_id, reminder.title if title is None else title, moment,
                reminder.notes if notes is None else notes,
                reminder.recurrence if repeat is None else repeat))}
        event = store.event(entry_id)
        if event is None:
            raise ValueError("No reminder or event has that ID; use list_agenda or search_agenda to find it")
        if remind_at:
            raise ValueError("Events take starts_at and ends_at instead of remind_at")
        starts = _moment(starts_at, "starts_at") if starts_at else event.starts_at
        ends = _moment(ends_at, "ends_at") if ends_at else starts + (event.ends_at - event.starts_at)
        return {"ok": True, "event": _event(store.update_event(
            entry_id, event.title if title is None else title, starts, ends,
            all_day=event.all_day if all_day is None else all_day,
            notes=event.notes if notes is None else notes,
            recurrence=event.recurrence if repeat is None else repeat))}
    except Exception as error:
        return {"ok": False, "error": str(error)}


def delete_agenda_entry(entry_id: str) -> dict:
    """Delete one Nova reminder or event by exact ID from list_agenda, on explicit user request."""
    try:
        store = _shared()
        deleted = store.delete_reminder(entry_id) or store.delete_event(entry_id)
        return {"ok": deleted, "deleted": deleted}
    except Exception as error:
        return {"ok": False, "error": str(error)}
