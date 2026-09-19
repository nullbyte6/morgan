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
"""Nonblocking Win32 keyboard events."""

import ctypes
from ctypes import wintypes as wt


class KeyEvent(ctypes.Structure):
    _fields_ = [("down", wt.BOOL), ("repeat", wt.WORD),
                ("key", wt.WORD), ("scan", wt.WORD),
                ("character", wt.WCHAR), ("modifiers", wt.DWORD)]


class MouseEvent(ctypes.Structure):
    _fields_ = [("x", wt.SHORT), ("y", wt.SHORT),
                ("buttons", wt.DWORD), ("modifiers", wt.DWORD),
                ("flags", wt.DWORD)]


class EventData(ctypes.Union):
    _fields_ = [("key", KeyEvent), ("mouse", MouseEvent),
                ("padding", ctypes.c_byte * 16)]


class InputRecord(ctypes.Structure):
    _fields_ = [("type", wt.WORD), ("event", EventData)]


class ConsoleInput:
    def __init__(self):
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        for name, args in {
            "GetStdHandle": [wt.DWORD],
            "GetConsoleMode": [wt.HANDLE, ctypes.POINTER(wt.DWORD)],
            "SetConsoleMode": [wt.HANDLE, wt.DWORD],
            "GetNumberOfConsoleInputEvents": [wt.HANDLE, ctypes.POINTER(wt.DWORD)],
            "ReadConsoleInputW": [wt.HANDLE, ctypes.POINTER(InputRecord),
                                  wt.DWORD, ctypes.POINTER(wt.DWORD)],
        }.items():
            function = getattr(self.kernel, name)
            function.argtypes = args
            function.restype = wt.HANDLE if name == "GetStdHandle" else wt.BOOL
        self.handle = self.kernel.GetStdHandle(-10)
        mode = wt.DWORD()
        self._check(self.kernel.GetConsoleMode(self.handle, ctypes.byref(mode)))
        self.mode = mode.value
        self._check(self.kernel.SetConsoleMode(
            self.handle, (self.mode | 0x88) & ~(0x10 | 0x40 | 0x2 | 0x4 | 0x200)))

    def suspend(self):
        """Restore the console mode for external interactive applications."""
        self._check(
            self.kernel.SetConsoleMode(self.handle, self.mode)
        )

    def resume(self):
        """Restore your own custom console input mode."""
        self._check(self.kernel.SetConsoleMode(
                self.handle,
                (self.mode | 0x88) & ~(0x10 | 0x40 | 0x2 | 0x4 | 0x200)
            ))

    @staticmethod
    def _check(result):
        if not result:
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        self._check(self.kernel.SetConsoleMode(self.handle, self.mode))

    def poll(self):
        count = wt.DWORD()
        self._check(
            self.kernel.GetNumberOfConsoleInputEvents(
                self.handle, ctypes.byref(count)))

        if not count.value:
            return []

        record = InputRecord()
        self._check(
            self.kernel.ReadConsoleInputW(
                self.handle, ctypes.byref(record), 1, ctypes.byref(count)))

        if record.type == 1 and record.event.key.down:
            key = record.event.key
            special = {
                0x25: "K",
                0x27: "M",
                0x24: "G",
                0x23: "O",
                0x2E: "S",
            }

            if key.key in special:
                return [("key", "\xe0" + special[key.key])] * key.repeat

            if key.character != "\x00":
                return [("key", key.character)] * key.repeat

        return []
