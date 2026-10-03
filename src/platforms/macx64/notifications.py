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
"""Notification Center banners and button dialogs through AppleScript."""

from src.init.lang import tr
import subprocess

MAX_BUTTONS = 3

NOTIFY = """on run argv
    display notification (item 2 of argv) with title (item 1 of argv)
end run"""

DIALOG = """on run argv
    set labels to {}
    repeat with position from 4 to count of argv
        set end of labels to item position of argv
    end repeat
    set answer to display dialog (item 2 of argv) with title (item 1 of argv) buttons labels ¬
        default button (count of labels) giving up after ((item 3 of argv) as integer)
    if gave up of answer then return ""
    return button returned of answer
end run"""


def _osascript(script, arguments, timeout):
    return subprocess.run(["osascript", "-e", script, *arguments], capture_output=True,
                          text=True, errors="replace", timeout=timeout)


def notify(title, message, app_name):
    result = _osascript(NOTIFY, [title, message], 25)
    if result.returncode:
        raise OSError((result.stderr or result.stdout).strip() or tr('notifications.notification_failed'))


def chosen_action(actions, label):
    return next((action for action, text in actions if text == label), "")


def ask_notification(title, message, actions, wait_seconds, app_name):
    shown = list(actions)[:MAX_BUTTONS]
    if not shown:
        notify(title, message, app_name)
        return ""
    try:
        result = _osascript(DIALOG, [title, message, str(int(wait_seconds)),
                                     *(label for _action, label in shown)], wait_seconds + 30)
    except subprocess.TimeoutExpired:
        return ""
    if result.returncode:
        notify(title, message, app_name)
        return ""
    return chosen_action(shown, result.stdout.strip())
