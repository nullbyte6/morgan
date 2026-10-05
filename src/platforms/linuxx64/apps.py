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
"""Package manager commands, per-app data folders and the Steam installation on Linux."""

from src.init.lang import tr
import os
from pathlib import Path
import shutil

COMMANDS = {
    "pacman": {"search": ["-Ss"], "list": ["-Q"], "install": ["-S"], "download": ["-Sw"], "uninstall": ["-R"]},
    "apt": {"search": ["search"], "list": ["list", "--installed"], "install": ["install"],
            "download": ["download"], "uninstall": ["remove"]},
    "dnf": {"search": ["search"], "list": ["list", "--installed"], "install": ["install"],
            "download": ["download"], "uninstall": ["remove"]},
    "zypper": {"search": ["search"], "list": ["search", "--installed-only"], "install": ["install"],
               "download": ["install", "--download-only"], "uninstall": ["remove"]},
}
SILENT = {"pacman": ["--noconfirm"], "apt": ["-y"], "dnf": ["-y"], "zypper": ["--non-interactive"]}
PURGE = {"pacman": ["-Rns"], "apt": ["purge"]}
QUERIES = ("search", "list")


def _manager():
    manager = next((name for name in COMMANDS if shutil.which(name)), None)
    if not manager:
        raise ValueError(tr('platforms.package_manager_unavailable'))
    return manager


def package_command(operation, package, option=False):
    manager = _manager()
    arguments = COMMANDS[manager].get(operation)
    if arguments is None:
        raise ValueError(operation)
    if operation == "uninstall" and option and manager in PURGE:
        arguments = PURGE[manager]
    command = [manager, *arguments]
    if option and operation == "install":
        command += SILENT[manager]
    if operation != "list":
        command.append(package)
    return command


def app_data_roots():
    home = Path.home()
    candidates = (Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share"),
                  Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config"),
                  Path(os.environ.get("XDG_CACHE_HOME") or home / ".cache"))
    return [root for root in candidates if root.is_dir()]


def steam_path():
    home = Path.home()
    data = Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share")
    for path in (data / "Steam", home / ".steam" / "steam",
                 home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam"):
        if path.is_dir():
            return path
    return None
