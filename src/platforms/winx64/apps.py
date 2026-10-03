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
"""winget commands, per-app data folders and the Steam installation on Windows."""

from src.init.lang import tr
import os
from pathlib import Path
import shutil


def _winget():
    executable = shutil.which("winget")
    if not executable and os.environ.get("LOCALAPPDATA"):
        alias = Path(
            os.environ["LOCALAPPDATA"]) / "Microsoft/WindowsApps/winget.exe"
        if alias.is_file():
            executable = str(alias)
    if not executable:
        raise ValueError(
            tr('app_manager.winget_is_unavailable_install_update_microsoft_app_installer_and'))
    return executable


def package_command(operation, package, option=False):
    if operation in ("search", "list"):
        arguments = [operation, "--query", package]
    elif operation in ("install", "download"):
        arguments = [operation, "--id", package, "--exact", "--source", "winget",
                     "--accept-package-agreements"]
        if option:
            arguments.append("--silent")
    elif operation == "uninstall":
        arguments = ["uninstall", "--id", package, "--exact", "--silent"]
        if option:
            arguments.append("--purge")
    else:
        raise ValueError(operation)
    return [_winget(), *arguments, "--accept-source-agreements",
            "--disable-interactivity"]


def app_data_roots():
    return [Path(os.environ[key]).absolute() for key in
            ("LOCALAPPDATA", "APPDATA", "PROGRAMDATA")
            if os.environ.get(key)]


def steam_path():
    import winreg

    keys = (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")
    )

    for root, key_path in keys:
        try:
            with winreg.OpenKey(root, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "SteamPath")
                path = Path(value)
                if (path / "steam.exe").is_file():
                    return path
        except OSError:
            continue

    system_drive = Path(os.environ.get("SystemDrive", "C:") + os.sep)
    candidates = [
        system_drive / "Steam",
        Path(os.environ.get("ProgramFiles", system_drive / "Program Files")) / "Steam",
        Path(os.environ.get("ProgramFiles(x86)", system_drive / "Program Files (x86)")) / "Steam",
    ]
    return next((path for path in candidates
                 if (path / "steam.exe").is_file()), None)
