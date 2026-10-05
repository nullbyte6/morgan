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
"""Desktop notifications and button prompts through notify-send."""

from src.init.lang import tr
import shutil
import subprocess

MAX_BUTTONS = 3


def _notify_send():
    executable = shutil.which("notify-send")
    if not executable:
        raise OSError(tr('notifications.notification_failed'))
    return executable


def notify(title, message, app_name):
    result = subprocess.run([_notify_send(), "--app-name", app_name, title, message],
                            capture_output=True, text=True, errors="replace", timeout=25)
    if result.returncode:
        raise OSError((result.stderr or result.stdout).strip() or tr('notifications.notification_failed'))


def ask_notification(title, message, actions, wait_seconds, app_name):
    shown = list(actions)[:MAX_BUTTONS]
    if not shown:
        notify(title, message, app_name)
        return ""
    command = [_notify_send(), "--app-name", app_name, "--wait", "--expire-time",
               str(int(wait_seconds) * 1000)]
    for action, label in shown:
        command += ["--action", f"{action}={label}"]
    try:
        result = subprocess.run([*command, title, message], capture_output=True, text=True,
                                errors="replace", timeout=wait_seconds + 30)
    except subprocess.TimeoutExpired:
        return ""
    if result.returncode:
        notify(title, message, app_name)
        return ""
    chosen = result.stdout.strip()
    return chosen if any(action == chosen for action, _label in shown) else ""
