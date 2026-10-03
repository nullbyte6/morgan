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
"""Windows processes, power, registered applications, file opening and the Recycle Bin."""

from src.init.lang import tr
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def open_path(path):
    os.startfile(path)


def terminate_process(process, force=False, include_children=False):
    from src.init.identity import get_assistant

    target = process.strip()
    if not target:
        return tr('brain.error_process_pid_or_image_name_is_required')

    command = ["taskkill.exe"]
    if target.isdecimal():
        process_id = int(target)
        if process_id <= 4:
            return tr('brain.refusing_to_terminate_a_critical_system_pid', process_id=process_id)
        if process_id == os.getpid():
            return tr('brain.refusing_to_terminate_s_own_pid', value0=get_assistant().name, process_id=process_id)
        command.extend(["/PID", str(process_id)])
        description = f"PID {process_id}"
    else:
        forbidden_characters = set('<>:"/\\|?*')
        if forbidden_characters.intersection(target):
            return tr('brain.error_invalid_process_image_name', target=target)
        image_name = target if target.casefold().endswith(
            ".exe") else f"{target}.exe"
        protected_images = {
            "registry",
            "registry.exe",
            "system",
            "system.exe",
            "system idle process",
            "system idle process.exe",
            "csrss.exe",
            "lsass.exe",
            "services.exe",
            "smss.exe",
            "wininit.exe",
            "winlogon.exe",
            Path(sys.executable).name.casefold(),
        }
        if image_name.casefold() in protected_images:
            return tr('brain.refusing_to_terminate_a_critical_or_current_process', image_name=image_name)
        command.extend(["/IM", image_name])
        description = image_name

    if force:
        command.append("/F")
    if include_children:
        command.append("/T")

    try:
        result = subprocess.run(
            command, capture_output=True, text=True, errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            return tr('brain.error_terminating', description=description, value1=detail or tr('brain.taskkill_failed'))
        return tr('brain.process_terminated', description=description)
    except OSError as error:
        return f"Error: {error}"


def _shutdown(arguments):
    executable = shutil.which("shutdown.exe") or "shutdown.exe"
    result = subprocess.run(
        [executable, *arguments],
        capture_output=True,
        text=True,
        errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return result.returncode == 0, (result.stderr or result.stdout).strip()


def schedule_shutdown(delay_seconds, reason):
    return _shutdown(["/s", "/t", str(delay_seconds), "/c", reason])


def cancel_shutdown():
    return _shutdown(["/a"])


def _app_paths():
    import winreg

    registry_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
    locations = (
        (winreg.HKEY_CURRENT_USER, winreg.KEY_READ),
        (winreg.HKEY_LOCAL_MACHINE,
         winreg.KEY_READ | winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE,
         winreg.KEY_READ | winreg.KEY_WOW64_32KEY),
    )
    apps = {}
    for hive, access in locations:
        try:
            with winreg.OpenKey(hive, registry_path, 0, access) as parent:
                subkey_count = winreg.QueryInfoKey(parent)[0]
                for index in range(subkey_count):
                    subkey_name = winreg.EnumKey(parent, index)
                    try:
                        with winreg.OpenKey(parent, subkey_name) as subkey:
                            executable = winreg.QueryValueEx(subkey, None)[0]
                    except OSError:
                        continue
                    executable = os.path.expandvars(str(executable)).strip('"')
                    if Path(executable).is_file():
                        key = executable.casefold()
                        apps[key] = {
                            "Name": Path(subkey_name).stem,
                            "Path": executable,
                        }
        except OSError:
            continue
    return list(apps.values())


def installed_applications():
    start_apps = []
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", "Get-StartApps | "
                                                         "Select-Object Name,AppID | "
                                                         "ConvertTo-Json -Compress"],
            capture_output=True, text=True, encoding="utf-8",
            creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode == 0:
            data = json.loads(result.stdout or "[]")
            start_apps = data if isinstance(data, list) else [data]
    except (OSError, json.JSONDecodeError):
        pass

    apps = [app for app in start_apps
            if app.get("Name") and app.get("AppID")]
    apps.extend(_app_paths())
    return apps


def empty_recycle_bin():
    import winshell

    winshell.recycle_bin().empty(confirm=False, show_progress=False, sound=True)
