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
"""Session-local timers and Windows notifications, without blocking input."""

from src.init.lang import tr
from .identity import get_assistant


import base64
import json
import os
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from xml.sax.saxutils import escape


_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$data = [Console]::In.ReadToEnd() | ConvertFrom-Json
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$icon = New-Object System.Windows.Forms.NotifyIcon
try {
    $icon.Icon = [System.Drawing.SystemIcons]::Information
    $icon.Text = $data.assistant_name
    $icon.Visible = $true
    $icon.ShowBalloonTip(10000, $data.title, $data.message,
        [System.Windows.Forms.ToolTipIcon]::Info)
    $until = [DateTime]::UtcNow.AddSeconds(10)
    while ([DateTime]::UtcNow -lt $until) {
        [System.Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds 100
    }
} finally {
    $icon.Dispose()
}
"""
_TOAST_APP = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
_lock = threading.Lock()
_timers = {}


def _validate(title, message):
    for name, value, limit in (("title", title, 63), ("message", message, 255)):
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise ValueError(tr('notifications.must_contain_1_to_characters', name=name, limit=limit))


def _deliver(title, message):
    if os.name != "nt":
        raise OSError(tr('notifications.notifications_are_only_supported_on_windows'))
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-STA",
         "-WindowStyle", "Hidden", "-EncodedCommand",
         base64.b64encode(_SCRIPT.encode("utf-16-le")).decode("ascii")],
        input=json.dumps({"title": title, "message": message,
                          "assistant_name": get_assistant().name[:63]}, ensure_ascii=True),
        capture_output=True, text=True, errors="replace", timeout=25,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise OSError((result.stderr or result.stdout).strip() or tr('notifications.notification_failed'))


def ask_notification(title: str, message: str, actions: list[tuple[str, str]], wait_seconds: int = 900) -> str:
    """Show a Windows notification with buttons and return the ID of the one pressed, "open" for a
    click on the notification itself, or an empty string when it was dismissed or left alone.
    Falls back to a plain notification without buttons where Windows cannot show one."""
    _validate(title, message)
    if os.name != "nt":
        raise OSError(tr('notifications.notifications_are_only_supported_on_windows'))
    try:
        from winrt.windows.data.xml.dom import XmlDocument
        from winrt.windows.ui.notifications import (ToastActivatedEventArgs, ToastDismissalReason,
                                                    ToastNotification, ToastNotificationManager)
    except ImportError:
        _deliver(title, message)
        return ""
    buttons = "".join(f'<action content="{escape(label)}" arguments="{escape(action)}" activationType="foreground"/>'
                      for action, label in actions)
    document = XmlDocument()
    document.load_xml(f'<toast scenario="reminder" launch="open"><visual><binding template="ToastGeneric">'
                      f'<text>{escape(title)}</text><text>{escape(message)}</text></binding></visual>'
                      f'<actions>{buttons}</actions></toast>')
    toast = ToastNotification(document)
    toast.tag = uuid4().hex[:16]
    toast.group = "nova"
    toast.expiration_time = datetime.now(timezone.utc) + timedelta(seconds=wait_seconds)
    answer = {"choice": "", "failed": False}
    finished = threading.Event()

    def activated(_toast, args):
        answer["choice"] = ToastActivatedEventArgs._from(args).arguments
        finished.set()

    def dismissed(_toast, args):
        if args.reason != ToastDismissalReason.TIMED_OUT:
            finished.set()

    def failed(_toast, _args):
        answer["failed"] = True
        finished.set()

    tokens = (toast.add_activated(activated), toast.add_dismissed(dismissed), toast.add_failed(failed))
    try:
        ToastNotificationManager.create_toast_notifier_with_id(_TOAST_APP).show(toast)
        finished.wait(wait_seconds)
    except OSError:
        answer["failed"] = True
    finally:
        toast.remove_activated(tokens[0])
        toast.remove_dismissed(tokens[1])
        toast.remove_failed(tokens[2])
        try:
            ToastNotificationManager.history.remove_grouped_tag_with_id(toast.tag, toast.group, _TOAST_APP)
        except OSError:
            pass
    if answer["failed"]:
        _deliver(title, message)
        return ""
    return answer["choice"]


def send_notification(message: str, title: str | None = None) -> str:
    """Send a Windows notification now; Windows settings control its visibility."""
    try:
        title = get_assistant().name if title is None else title
        _validate(title, message)
        _deliver(title, message)
        return tr('notifications.notification_submitted_to_windows')
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        return tr('notifications.error_sending_notification', error=error)


def _fire(timer_id):
    with _lock:
        entry = _timers[timer_id]
        if entry["status"] != "pending":
            return
        entry["status"] = "sending"
    try:
        _deliver(entry["title"], entry["message"])
    except Exception as error:
        with _lock:
            entry["status"] = "failed"
            entry["error"] = str(error)
    else:
        with _lock:
            entry["status"] = "submitted"


def schedule_notification(delay_seconds: int, message: str, title: str | None = None) -> str:
    """Schedule a notification after 0–31536000 seconds. the assistant must stay running.
    Returns an ID for list_timers/cancel_timer. Timers survive reload, not exit.
    Displays a message only; does not execute commands or shut down the PC.
    Use shutdown_computer for a scheduled Windows shutdown.
    Use add_reminder instead for reminders at a date or time.
    """
    try:
        if os.name != "nt":
            raise ValueError(tr('notifications.notifications_are_only_supported_on_windows'))
        title = get_assistant().name if title is None else title
        _validate(title, message)
        if type(delay_seconds) is not int or not 0 <= delay_seconds <= 31_536_000:
            raise ValueError(tr('notifications.delay_seconds_must_be_an_integer_between_0_and_31536000'))
        timer_id = uuid4().hex
        timer = threading.Timer(delay_seconds, _fire, args=(timer_id,))
        timer.daemon = True
        with _lock:
            _timers[timer_id] = {
                "id": timer_id, "title": title, "message": message,
                "status": "pending",
                "due_at": (datetime.now().astimezone() + timedelta(seconds=delay_seconds)).isoformat(),
                "deadline": time.monotonic() + delay_seconds, "timer": timer,
            }
            try:
                timer.start()
            except Exception:
                del _timers[timer_id]
                raise
        return json.dumps({"id": timer_id, "status": "pending", "delay_seconds": delay_seconds,
                           "requires_arlo_running": True})
    except (OSError, ValueError, RuntimeError) as error:
        return tr('notifications.error_scheduling_notification', error=error)


def start_timer(duration_seconds: int, label: str = "Timer") -> str:
    """Start an internal countdown and notify Windows when it expires."""
    if type(duration_seconds) is not int or duration_seconds <= 0:
        return tr('notifications.error_duration_seconds_must_be_a_positive_integer')
    return schedule_notification(duration_seconds, label, tr('notifications.timer_finished', value0=get_assistant().name))


def list_timers() -> str:
    """List session timers, remaining seconds, notification status and errors."""
    with _lock:
        return json.dumps([
            {**{key: value for key, value in entry.items() if key not in ("timer", "deadline")},
             "remaining_seconds": max(0, round(entry["deadline"] - time.monotonic(), 1))
             if entry["status"] == "pending" else 0}
            for entry in _timers.values()
        ], ensure_ascii=False)


def cancel_timer(timer_id: str) -> str:
    """Cancel a pending timer or scheduled notification by its exact ID."""
    with _lock:
        entry = _timers.get(timer_id)
        if entry is None:
            return tr('notifications.error_timer_id_not_found')
        if entry["status"] != "pending":
            return tr('notifications.timer_is_already_cannot_cancel', value0=entry['status'])
        entry["status"] = "cancelled"
        entry["timer"].cancel()
    return tr('notifications.timer_cancelled', timer_id=timer_id)
