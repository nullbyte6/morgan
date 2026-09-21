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
"""Read current taskbar-style application windows through Win32."""

from src.init.lang import tr
import ctypes
from ctypes import wintypes as wt
import json
import os


def is_taskbar_window(visible, cloaked, style, owner, shell):
    """Apply standard Shell taskbar eligibility rules, including minimized apps."""
    return bool(visible and not cloaked and not shell
                and not style & 0x80
                and (style & 0x40000 or not owner))


def get_open_windows():
    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    dwm = ctypes.WinDLL("dwmapi", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def bind(dll, name, args, result):
        function = getattr(dll, name)
        function.argtypes = args
        function.restype = result
        return function

    enumerate_windows = bind(user, "EnumWindows", [callback_type, wt.LPARAM], wt.BOOL)
    visible = bind(user, "IsWindowVisible", [wt.HWND], wt.BOOL)
    minimized = bind(user, "IsIconic", [wt.HWND], wt.BOOL)
    owner = bind(user, "GetWindow", [wt.HWND, wt.UINT], wt.HWND)
    shell = bind(user, "GetShellWindow", [], wt.HWND)()
    style = bind(user, "GetWindowLongW", [wt.HWND, ctypes.c_int], wt.LONG)
    title_length = bind(user, "GetWindowTextLengthW", [wt.HWND], ctypes.c_int)
    title_text = bind(user, "GetWindowTextW", [wt.HWND, wt.LPWSTR, ctypes.c_int], ctypes.c_int)
    class_text = bind(user, "GetClassNameW", [wt.HWND, wt.LPWSTR, ctypes.c_int], ctypes.c_int)
    get_pid = bind(user, "GetWindowThreadProcessId", [wt.HWND, ctypes.POINTER(wt.DWORD)], wt.DWORD)
    attribute = bind(dwm, "DwmGetWindowAttribute",
                     [wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD], wt.LONG)
    open_process = bind(kernel, "OpenProcess", [wt.DWORD, wt.BOOL, wt.DWORD], wt.HANDLE)
    image_name = bind(kernel, "QueryFullProcessImageNameW",
                      [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)], wt.BOOL)
    close = bind(kernel, "CloseHandle", [wt.HANDLE], wt.BOOL)
    windows = []
    errors = []

    @callback_type
    def collect(hwnd, _):
        try:
            cloaked = wt.DWORD()
            attribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
            if not is_taskbar_window(visible(hwnd), cloaked.value,
                                     style(hwnd, -20), owner(hwnd, 4), hwnd == shell):
                return True
            class_name = ctypes.create_unicode_buffer(256)
            class_text(hwnd, class_name, len(class_name))
            if class_name.value in {"Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman", "WorkerW"}:
                return True
            title = ctypes.create_unicode_buffer(title_length(hwnd) + 1)
            title_text(hwnd, title, len(title))
            pid = wt.DWORD()
            get_pid(hwnd, ctypes.byref(pid))
            executable = None
            process = open_process(0x1000, False, pid.value)
            if process:
                try:
                    size = wt.DWORD(32768)
                    path = ctypes.create_unicode_buffer(size.value)
                    if image_name(process, 0, path, ctypes.byref(size)):
                        executable = path.value.rsplit("\\", 1)[-1]
                finally:
                    close(process)
            windows.append({"hwnd": int(hwnd), "title": title.value, "executable": executable,
                            "pid": pid.value, "minimized": bool(minimized(hwnd))})
        except Exception as error:
            errors.append(error)
            return False
        return True

    if not enumerate_windows(collect, 0):
        if errors:
            raise errors[0]
        error_code = ctypes.get_last_error()
        if error_code:
            raise ctypes.WinError(error_code)
        raise OSError(tr('windows.windows_could_not_enumerate_windows_in_this_desktop_session'))
    return windows


def request_window_close(hwnd, expected_pid):
    """Request normal closure, preserving save dialogs and the Explorer shell."""
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    user.GetWindowThreadProcessId.restype = wt.DWORD
    user.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    user.PostMessageW.restype = wt.BOOL
    pid = wt.DWORD()
    user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value != expected_pid:
        raise OSError(tr('windows.window_no_longer_belongs_to_the_selected_process'))
    if not user.PostMessageW(hwnd, 0x0010, 0, 0):
        raise ctypes.WinError(ctypes.get_last_error())


def minimize_all_windows(except_applications: list[str] | None = None) -> str:
    """Minimize taskbar windows, optionally keeping named apps visible."""
    exclusions = [
        value.strip().casefold() for value in (except_applications or [])
        if value.strip()
    ]
    context = {"except_applications": except_applications or []}
    if os.name != "nt":
        return json.dumps({
            **context,
            "status": "error",
            "error": "Window minimization is only supported on Windows",
        }, ensure_ascii=False)

    try:
        user = ctypes.WinDLL("user32", use_last_error=True)
        user.ShowWindowAsync.argtypes = [wt.HWND, ctypes.c_int]
        user.ShowWindowAsync.restype = wt.BOOL
        minimized = []
        kept = []
        failures = []
        for window in get_open_windows():
            identity = " ".join((
                window.get("title") or "",
                window.get("executable") or "",
            )).casefold()
            if any(exclusion in identity for exclusion in exclusions):
                kept.append(window.get("title") or window.get("executable"))
                continue
            if window["minimized"]:
                continue
            if user.ShowWindowAsync(window["hwnd"], 6):
                minimized.append(window.get("title") or window.get("executable"))
            else:
                failures.append(window.get("title") or window.get("executable"))
        return json.dumps({
            **context,
            "status": "completed" if not failures else "partial",
            "minimized": minimized,
            "kept": kept,
            "failures": failures,
        }, ensure_ascii=False)
    except (OSError, ValueError) as error:
        return json.dumps({
            **context,
            "status": "error",
            "error": str(error),
        }, ensure_ascii=False)
