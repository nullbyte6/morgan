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
"""Resolve user folders, including Windows folder redirection."""

from src.init.lang import tr
import ctypes
import os
from pathlib import Path
from uuid import UUID


KNOWN_FOLDERS = {
    "documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
    "desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
    "downloads": "374DE290-123F-4565-9164-39C4925E467B",
}
FOLDER_ALIASES = {
    "documentos": "documents", "documents": "documents",
    "mis documentos": "documents", "my documents": "documents",
    "escritorio": "desktop", "desktop": "desktop",
    "descargas": "downloads", "downloads": "downloads",
    "home": "home", "~": "home", "inicio": "home",
    "directorio actual": ".", "carpeta actual": ".",
    "current directory": ".", "current folder": ".",
}


def known_folder_path(name):
    if os.name != "nt":
        return Path.home() / name.capitalize()
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


def resolve_directory(path):
    path = path.strip()
    if len(path) >= 2 and path[0] == path[-1] and path[0] in "\"'":
        path = path[1:-1]
    if not path:
        path = "."
    alias = FOLDER_ALIASES.get(path.casefold())
    if alias == "home":
        return Path.home().resolve()
    if alias in KNOWN_FOLDERS:
        return known_folder_path(alias).resolve()
    return Path(os.path.expandvars(alias or path)).expanduser().resolve()
