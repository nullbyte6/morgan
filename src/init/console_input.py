"""Nonblocking Win32 console events, including the mouse wheel."""

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
        # Mouse/window events; disable Quick Edit, line/echo and VT input.
        self._check(self.kernel.SetConsoleMode(
            self.handle, (self.mode | 0x98) & ~(0x40 | 0x2 | 0x4 | 0x200)))

    @staticmethod
    def _check(result):
        if not result:
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        self._check(self.kernel.SetConsoleMode(self.handle, self.mode))

    def poll(self):
        count = wt.DWORD()
        self._check(self.kernel.GetNumberOfConsoleInputEvents(
            self.handle, ctypes.byref(count)))
        if not count.value:
            return []
        record = InputRecord()
        self._check(self.kernel.ReadConsoleInputW(
            self.handle, ctypes.byref(record), 1, ctypes.byref(count)))
        if record.type == 2 and record.event.mouse.flags & 0x4:
            delta = ctypes.c_short(record.event.mouse.buttons >> 16).value
            return [("scroll", 3 if delta > 0 else -3)] if delta else []
        if record.type == 1 and record.event.key.down:
            key = record.event.key
            navigation = {0x26: 1, 0x28: -1, 0x21: "page_up", 0x22: "page_down"}
            if key.key in navigation:
                return [("scroll", navigation[key.key])] * key.repeat
            special = {0x25: "K", 0x27: "M", 0x24: "G", 0x23: "O", 0x2e: "S"}
            if key.key in special:
                return [("key", "\xe0" + special[key.key])] * key.repeat
            if key.character != "\x00":
                return [("key", key.character)] * key.repeat
        return []
