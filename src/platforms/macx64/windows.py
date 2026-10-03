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
"""Read, launch, quit and hide application windows through Quartz and AppKit."""

from src.init.lang import tr
import os
from pathlib import Path
import subprocess
import time

MINIMUM_SIZE = 50


def _window_list():
    import Quartz
    options = Quartz.kCGWindowListOptionAll | Quartz.kCGWindowListExcludeDesktopElements
    return Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID) or []


def application_windows(entries):
    """Keep visible normal-layer windows, the ones the Dock and Mission Control show."""
    windows = []
    for entry in entries:
        bounds = entry.get("kCGWindowBounds") or {}
        if (entry.get("kCGWindowLayer", 0) != 0 or entry.get("kCGWindowAlpha", 1) <= 0
                or bounds.get("Width", 0) < MINIMUM_SIZE or bounds.get("Height", 0) < MINIMUM_SIZE):
            continue
        windows.append({"hwnd": int(entry["kCGWindowNumber"]), "title": entry.get("kCGWindowName") or "",
                        "executable": entry.get("kCGWindowOwnerName"), "executable_path": None,
                        "app_id": None, "pid": int(entry.get("kCGWindowOwnerPID", 0)),
                        "minimized": not entry.get("kCGWindowIsOnscreen", False)})
    return windows


def _application(pid):
    from AppKit import NSApplicationActivationPolicyRegular, NSRunningApplication
    application = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    if application is None or application.activationPolicy() != NSApplicationActivationPolicyRegular:
        return None
    return application


def get_open_windows():
    windows = []
    applications = {}
    for window in application_windows(_window_list()):
        pid = window["pid"]
        if pid not in applications:
            applications[pid] = _application(pid)
        application = applications[pid]
        if application is None:
            continue
        executable = application.executableURL()
        window.update(executable_path=executable.path() if executable is not None else None,
                      app_id=application.bundleIdentifier())
        windows.append(window)
    return windows


def launch_application(target, timeout=8.0):
    path = Path(target)
    command = ["open", str(path)] if path.exists() else ["open", "-a", target]
    result = subprocess.run(command, capture_output=True, text=True, errors="replace")
    if result.returncode:
        raise OSError((result.stderr or result.stdout).strip() or f"open exited with {result.returncode}")
    bundle = os.path.realpath(path) if path.exists() else None
    name = path.stem.casefold()
    deadline = time.monotonic() + timeout
    while True:
        try:
            windows = get_open_windows()
        except Exception as error:
            return {"status": "submitted", "opened": False,
                    "launch_requested": True, "error": str(error)}
        for window in windows:
            executable = window.get("executable_path")
            if ((bundle and executable and os.path.realpath(executable).startswith(bundle + os.sep))
                    or (window.get("executable") or "").casefold() == name):
                return {"status": "completed", "opened": True, "window": window}
        if time.monotonic() >= deadline:
            return {"status": "timeout", "opened": False,
                    "launch_requested": True,
                    "error": "macOS accepted the launch but no matching application window was confirmed. Do not claim it opened or automatically launch it again."}
        time.sleep(0.2)


def _owned_application(hwnd, expected_pid=None):
    owner = next((window for window in application_windows(_window_list())
                  if window["hwnd"] == int(hwnd)), None)
    if owner is None or (expected_pid is not None and owner["pid"] != expected_pid):
        raise OSError(tr('windows.window_no_longer_belongs_to_the_selected_process'))
    application = _application(owner["pid"])
    if application is None:
        raise OSError(tr('windows.window_no_longer_belongs_to_the_selected_process'))
    return application


def request_window_close(hwnd, expected_pid):
    if not _owned_application(hwnd, expected_pid).terminate():
        raise OSError(tr('platforms.quit_request_refused'))


def minimize_window(hwnd):
    return bool(_owned_application(hwnd).hide())
