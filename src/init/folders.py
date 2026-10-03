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
"""Resolve user folders through the active platform, including folder redirection."""

import os
from pathlib import Path

from src.platforms import current_platform


KNOWN_FOLDERS = ("documents", "desktop", "downloads")
FOLDER_ALIASES = {
    "documentos": "documents", "documents": "documents",
    "mis documentos": "documents", "my documents": "documents",
    "escritorio": "desktop", "desktop": "desktop",
    "descargas": "downloads", "downloads": "downloads",
    "home": "home", "~": "home", "inicio": "home",
    "directorio actual": ".", "carpeta actual": ".",
    "current directory": ".", "current folder": ".",
}


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
        return current_platform().known_folder(alias).resolve()
    return Path(os.path.expandvars(alias or path)).expanduser().resolve()
