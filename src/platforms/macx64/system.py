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
"""macOS processes, power, installed applications and the Trash."""

from src.init.lang import tr
import os
from pathlib import Path
import subprocess
import sys

import psutil

SHUTDOWN_MARKER = "arlo-shutdown"
APPLICATION_FOLDERS = ("/Applications", "/Applications/Utilities", "/System/Applications",
                       "/System/Applications/Utilities", "~/Applications")
PROTECTED_PROCESSES = {"kernel_task", "launchd", "windowserver", "loginwindow", "logd",
                       "securityd", "opendirectoryd", "systemstats", "watchdogd"}


def _osascript(script):
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True,
                            errors="replace", timeout=30)
    if result.returncode:
        raise OSError((result.stderr or result.stdout).strip() or f"osascript exited with {result.returncode}")
    return result.stdout.strip()


def terminate_process(process, force=False, include_children=False):
    from src.init.identity import get_assistant

    target = process.strip()
    if not target:
        return tr('brain.error_process_pid_or_image_name_is_required')
    if target.isdecimal():
        process_id = int(target)
        if process_id <= 1:
            return tr('brain.refusing_to_terminate_a_critical_system_pid', process_id=process_id)
        if process_id == os.getpid():
            return tr('brain.refusing_to_terminate_s_own_pid', value0=get_assistant().name, process_id=process_id)
        description = f"PID {process_id}"
        try:
            processes = [psutil.Process(process_id)]
        except psutil.NoSuchProcess:
            return tr('brain.error_terminating', description=description, value1=tr('platforms.no_matching_process'))
    else:
        if "/" in target or "\x00" in target:
            return tr('brain.error_invalid_process_image_name', target=target)
        if target.casefold() in PROTECTED_PROCESSES | {Path(sys.executable).name.casefold()}:
            return tr('brain.refusing_to_terminate_a_critical_or_current_process', image_name=target)
        description = target
        processes = [candidate for candidate in psutil.process_iter(["name"])
                     if (candidate.info["name"] or "").casefold() == target.casefold()
                     and candidate.pid != os.getpid()]
        if not processes:
            return tr('brain.error_terminating', description=description, value1=tr('platforms.no_matching_process'))

    targets = []
    try:
        for candidate in processes:
            if include_children:
                targets.extend(candidate.children(recursive=True))
            targets.append(candidate)
        for candidate in targets:
            try:
                candidate.kill() if force else candidate.terminate()
            except psutil.NoSuchProcess:
                pass
        _gone, alive = psutil.wait_procs(targets, timeout=5)
    except (psutil.AccessDenied, psutil.NoSuchProcess) as error:
        return tr('brain.error_terminating', description=description, value1=str(error))
    if alive:
        return tr('brain.error_terminating', description=description, value1=tr('platforms.process_still_running'))
    return tr('brain.process_terminated', description=description)


def schedule_shutdown(delay_seconds, reason):
    subprocess.Popen(
        ["/bin/sh", "-c", "sleep \"$1\" && osascript -e 'tell application \"System Events\" to shut down'",
         SHUTDOWN_MARKER, str(delay_seconds)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)
    return True, ""


def cancel_shutdown():
    pending = [process for process in psutil.process_iter(["cmdline"])
               if SHUTDOWN_MARKER in (process.info["cmdline"] or [])]
    for process in pending:
        try:
            for child in process.children(recursive=True):
                child.kill()
            process.kill()
        except psutil.NoSuchProcess:
            pass
    return bool(pending), ""


def installed_applications(folders=APPLICATION_FOLDERS):
    applications = {}
    for folder in folders:
        try:
            entries = sorted(Path(folder).expanduser().iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.suffix.casefold() == ".app":
                applications.setdefault(entry.stem.casefold(), {"Name": entry.stem, "Path": str(entry)})
    return list(applications.values())


def empty_recycle_bin():
    _osascript('tell application "Finder" to empty trash')
