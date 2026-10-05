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
"""XDG user folders and the mounted local volumes."""

import os
from pathlib import Path

USER_DIRS = "user-dirs.dirs"
VOLUME_ROOTS = ("/media", "/run/media", "/mnt")


def known_folder(name):
    key = f"XDG_{name.upper()}_DIR"
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / USER_DIRS
    try:
        for line in config.read_text(encoding="utf-8").splitlines():
            variable, _, value = line.partition("=")
            if variable.strip() == key:
                return Path(os.path.expandvars(value.strip().strip('"')))
    except OSError:
        pass
    return Path.home() / name.capitalize()


def local_drives(removable=True, roots=VOLUME_ROOTS):
    drives = [Path("/")]
    if not removable:
        return drives
    for root in roots:
        try:
            entries = sorted(Path(root).iterdir())
        except OSError:
            continue
        for entry in entries:
            if os.path.ismount(entry):
                drives.append(entry)
            elif entry.is_dir() and not entry.is_symlink():
                try:
                    drives.extend(child for child in sorted(entry.iterdir()) if os.path.ismount(child))
                except OSError:
                    pass
    return list(dict.fromkeys(drives))
