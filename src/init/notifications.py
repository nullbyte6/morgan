"""Session-local timers and Windows notifications, without blocking input."""

import base64
import json
import os
import subprocess
import threading
import time
from datetime import datetime, timedelta
from uuid import uuid4


_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$data = [Console]::In.ReadToEnd() | ConvertFrom-Json
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$icon = New-Object System.Windows.Forms.NotifyIcon
try {
    $icon.Icon = [System.Drawing.SystemIcons]::Information
    $icon.Text = 'Nora'
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
_lock = threading.Lock()
_timers = {}


def _validate(title, message):
    for name, value, limit in (("title", title, 63), ("message", message, 255)):
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise ValueError(f"{name} must contain 1 to {limit} characters")


def _deliver(title, message):
    if os.name != "nt":
        raise OSError("Notifications are only supported on Windows")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-STA",
         "-WindowStyle", "Hidden", "-EncodedCommand",
         base64.b64encode(_SCRIPT.encode("utf-16-le")).decode("ascii")],
        input=json.dumps({"title": title, "message": message}, ensure_ascii=True),
        capture_output=True, text=True, errors="replace", timeout=25,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise OSError((result.stderr or result.stdout).strip() or "Notification failed")


def send_notification(message: str, title: str = "Nora") -> str:
    """Send a Windows notification now; Windows settings control its visibility."""
    try:
        _validate(title, message)
        _deliver(title, message)
        return "Notification submitted to Windows"
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        return f"Error sending notification: {error}"


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


def schedule_notification(delay_seconds: int, message: str, title: str = "Nora") -> str:
    """Schedule a notification after 0–31536000 seconds. Nora must stay running.
    Returns an ID for list_timers/cancel_timer. Timers survive reload, not exit.
    """
    try:
        if os.name != "nt":
            raise ValueError("Notifications are only supported on Windows")
        _validate(title, message)
        if type(delay_seconds) is not int or not 0 <= delay_seconds <= 31_536_000:
            raise ValueError("delay_seconds must be an integer between 0 and 31536000")
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
                           "requires_nora_running": True})
    except (OSError, ValueError, RuntimeError) as error:
        return f"Error scheduling notification: {error}"


def start_timer(duration_seconds: int, label: str = "Timer") -> str:
    """Start an internal countdown and notify Windows when it expires."""
    if type(duration_seconds) is not int or duration_seconds <= 0:
        return "Error: duration_seconds must be a positive integer"
    return schedule_notification(duration_seconds, label, "Nora — Timer finished")


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
            return "Error: timer ID not found"
        if entry["status"] != "pending":
            return f"Timer is already {entry['status']}; cannot cancel"
        entry["status"] = "cancelled"
        entry["timer"].cancel()
    return f"Timer {timer_id} cancelled"
