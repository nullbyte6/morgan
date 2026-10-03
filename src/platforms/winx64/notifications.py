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
"""Windows balloon and toast notifications."""

from src.init.lang import tr
import base64
import json
import subprocess
import threading
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


def notify(title, message, app_name):
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-STA",
         "-WindowStyle", "Hidden", "-EncodedCommand",
         base64.b64encode(_SCRIPT.encode("utf-16-le")).decode("ascii")],
        input=json.dumps({"title": title, "message": message,
                          "assistant_name": app_name}, ensure_ascii=True),
        capture_output=True, text=True, errors="replace", timeout=25,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise OSError((result.stderr or result.stdout).strip() or tr('notifications.notification_failed'))


def ask_notification(title, message, actions, wait_seconds, app_name):
    try:
        from winrt.windows.data.xml.dom import XmlDocument
        from winrt.windows.ui.notifications import (ToastActivatedEventArgs, ToastDismissalReason,
                                                    ToastNotification, ToastNotificationManager)
    except ImportError:
        notify(title, message, app_name)
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
        notify(title, message, app_name)
        return ""
    return answer["choice"]
