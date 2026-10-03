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
"""Homebrew commands, per-app data folders and the Steam installation on macOS."""

from src.init.lang import tr
from pathlib import Path
import shutil

HOMEBREW_PATHS = ("/opt/homebrew/bin/brew", "/usr/local/bin/brew")


def _brew():
    executable = shutil.which("brew") or next(
        (path for path in HOMEBREW_PATHS if Path(path).is_file()), None)
    if not executable:
        raise ValueError(tr('platforms.homebrew_unavailable'))
    return executable


def package_command(operation, package, option=False):
    arguments = {
        "search": ["search", package],
        "list": ["list", "--versions"],
        "install": ["install", package],
        "download": ["fetch", package],
        "uninstall": ["uninstall", package],
    }.get(operation)
    if arguments is None:
        raise ValueError(operation)
    return [_brew(), *arguments]


def app_data_roots():
    library = Path.home() / "Library"
    return [root for root in (library / "Application Support", library / "Caches") if root.is_dir()]


def steam_path():
    path = Path.home() / "Library" / "Application Support" / "Steam"
    return path if path.is_dir() else None
