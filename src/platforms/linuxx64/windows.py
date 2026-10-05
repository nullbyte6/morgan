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
"""Read, launch, close and minimize application windows through wmctrl, xdotool and gio."""

from src.init.lang import tr
import os
from pathlib import Path
import shutil
import subprocess
import time

import psutil

from . import services, system


def _run(command, timeout=10):
    return subprocess.run(command, capture_output=True, text=True, errors="replace",
                          timeout=timeout, env=services.system_environment())


def _wmctrl():
    executable = shutil.which("wmctrl")
    if not executable:
        raise OSError(tr('platforms.window_tools_unavailable'))
    return executable


def parse_windows(output):
    """Keep the normal windows from wmctrl -lpx: they have an owner process and a window class."""
    windows = []
    for line in output.splitlines():
        fields = line.split(None, 5)
        if len(fields) < 5 or not fields[2].isdecimal() or int(fields[2]) <= 0:
            continue
        handle, _desktop, pid, window_class = fields[:4]
        windows.append({"hwnd": int(handle, 16), "title": fields[5] if len(fields) > 5 else "",
                        "executable": None, "executable_path": None,
                        "app_id": window_class.partition(".")[2] or window_class,
                        "pid": int(pid), "minimized": False})
    return windows


def _hidden(handle):
    xprop = shutil.which("xprop")
    if not xprop:
        return False
    try:
        return "_NET_WM_STATE_HIDDEN" in _run([xprop, "-id", hex(handle), "_NET_WM_STATE"], 3).stdout
    except (OSError, subprocess.SubprocessError):
        return False


def get_open_windows():
    result = _run([_wmctrl(), "-lpx"])
    if result.returncode:
        raise OSError((result.stderr or result.stdout).strip() or f"wmctrl exited with {result.returncode}")
    windows = parse_windows(result.stdout)
    for window in windows:
        try:
            process = psutil.Process(window["pid"])
            window.update(executable=process.name(), executable_path=process.exe() or None)
        except (psutil.Error, OSError):
            pass
        window["minimized"] = _hidden(window["hwnd"])
    return windows


def _start(target):
    path = Path(target)
    environment = services.system_environment()
    options = dict(env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, start_new_session=True)
    if path.suffix == ".desktop" and path.is_file() and shutil.which("gio"):
        command = ["gio", "launch", str(path)]
    elif path.is_file() and os.access(path, os.X_OK):
        command = [str(path)]
    elif path.exists():
        command = ["xdg-open", str(path)]
    else:
        match = next((entry for entry in system.installed_applications()
                      if entry["Name"].casefold() == target.casefold()), None)
        if match and shutil.which("gio"):
            command = ["gio", "launch", match["Path"]]
        elif shutil.which(target):
            command = [target]
        else:
            raise OSError(f"{target}: application not found")
    return subprocess.Popen(command, **options), command


def launch_application(target, timeout=8.0):
    process, command = _start(target)
    names = {Path(target).stem.casefold(), Path(command[-1]).stem.casefold()}
    deadline = time.monotonic() + timeout
    while True:
        try:
            windows = get_open_windows()
        except Exception as error:
            return {"status": "submitted", "opened": False,
                    "launch_requested": True, "error": str(error)}
        for window in windows:
            if (window["pid"] == process.pid
                    or (window.get("executable") or "").casefold() in names
                    or (window.get("app_id") or "").casefold() in names):
                return {"status": "completed", "opened": True, "window": window}
        if time.monotonic() >= deadline:
            return {"status": "timeout", "opened": False,
                    "launch_requested": True,
                    "error": "The launch was accepted but no matching application window was confirmed. Do not claim it opened or automatically launch it again."}
        time.sleep(0.2)


def _owned(handle, expected_pid=None):
    owner = next((window for window in get_open_windows() if window["hwnd"] == int(handle)), None)
    if owner is None or (expected_pid is not None and owner["pid"] != expected_pid):
        raise OSError(tr('windows.window_no_longer_belongs_to_the_selected_process'))
    return owner


def request_window_close(hwnd, expected_pid):
    _owned(hwnd, expected_pid)
    result = _run([_wmctrl(), "-ic", hex(int(hwnd))])
    if result.returncode:
        raise OSError(tr('platforms.quit_request_refused'))


def minimize_window(hwnd):
    _owned(hwnd)
    xdotool = shutil.which("xdotool")
    if not xdotool:
        raise OSError(tr('platforms.window_tools_unavailable'))
    return _run([xdotool, "windowminimize", str(int(hwnd))]).returncode == 0
