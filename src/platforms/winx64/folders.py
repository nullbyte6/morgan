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
"""Resolve Windows known folders, including redirection, and local drive roots."""

from src.init.lang import tr
import ctypes
from pathlib import Path
from uuid import UUID


KNOWN_FOLDERS = {
    "documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
    "desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
    "downloads": "374DE290-123F-4565-9164-39C4925E467B",
}


def known_folder(name):
    identifier = (ctypes.c_ubyte * 16).from_buffer_copy(UUID(KNOWN_FOLDERS[name]).bytes_le)
    shell = ctypes.WinDLL("shell32")
    ole = ctypes.WinDLL("ole32")
    get_path = shell.SHGetKnownFolderPath
    get_path.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p,
                        ctypes.POINTER(ctypes.c_wchar_p)]
    get_path.restype = ctypes.c_long
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole.CoTaskMemFree.restype = None
    value = ctypes.c_wchar_p()
    try:
        result = get_path(ctypes.byref(identifier), 0, None, ctypes.byref(value))
        if result < 0:
            raise OSError(tr('folders.cannot_resolve_hresult_0x', name=name, value1=result & 0xffffffff))
        return Path(value.value)
    finally:
        if value:
            ole.CoTaskMemFree(ctypes.cast(value, ctypes.c_void_p))


def local_drives(removable=True):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetLogicalDrives.restype = ctypes.c_uint32
    kernel.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
    kernel.GetDriveTypeW.restype = ctypes.c_uint
    mask = kernel.GetLogicalDrives()
    if not mask:
        raise ctypes.WinError(ctypes.get_last_error())
    types = (2, 3) if removable else (3,)
    return [Path(f"{chr(65 + index)}:\\") for index in range(26)
            if mask & (1 << index)
            and kernel.GetDriveTypeW(f"{chr(65 + index)}:\\") in types]
