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
            "completed": reminder.is_completed}


def _event(event) -> dict:
    return {"id": event.id, "kind": "event", "title": event.title, "notes": event.notes,
            "starts_at": event.starts_at.isoformat(timespec="minutes"),
            "ends_at": event.ends_at.isoformat(timespec="minutes"), "all_day": event.all_day}


def _entry(entry) -> dict:
    return _event(entry) if hasattr(entry, "starts_at") else _reminder(entry)


def add_reminder(title: str, remind_at: str, notes: str = "") -> dict:
    """Save a reminder in Nova, the user's agenda, announced as a Windows notification when due.
    remind_at is local wall-clock time as ISO, e.g. 2026-10-02T09:30; check get_current_time
    for relative requests. Persists across restarts. Prefer this over schedule_notification
    for anything the user asks to be reminded of at a date or time.
    """
    try:
        moment = _moment(remind_at, "remind_at")
        if moment < datetime.now() - timedelta(minutes=1):
            raise ValueError("remind_at is in the past")
        return {"ok": True, "reminder": _reminder(_shared().add_reminder(title, moment, notes))}
    except Exception as error:
        return {"ok": False, "error": str(error)}


def add_event(title: str, starts_at: str, ends_at: str | None = None,
              all_day: bool = False, notes: str = "") -> dict:
    """Save an event in Nova's calendar. Times are local ISO, e.g. 2026-10-02T18:00.
    ends_at defaults to one hour after starts_at, or the same day when all_day.
    """
    try:
        starts = _moment(starts_at, "starts_at")
        if ends_at:
            ends = _moment(ends_at, "ends_at")
        else:
            ends = starts if all_day else starts + timedelta(hours=1)
        return {"ok": True, "event": _event(_shared().add_event(title, starts, ends,
                                                               all_day=all_day, notes=notes))}
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


def complete_reminder(reminder_id: str, completed: bool = True) -> dict:
    """Mark a Nova reminder as done, or pending again with completed false. Use IDs from list_agenda."""
    try:
        return {"ok": True, "reminder": _reminder(_shared().set_reminder_completed(reminder_id, completed))}
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
