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
"""Desktop launching on Linux: the installed Morgan executable, or the desktop entry from source."""

import sys


def set_app_id(app_id):
    try:
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.setDesktopFileName("morgan")
    except Exception:
        pass


def desktop_launcher(installation, root):
    if installation is not None and installation.is_dir():
        executable = installation / "Morgan"
        if executable.is_file():
            return executable
    return root / "entry" / "desktop.py"


def launch_command(launcher, root):
    if launcher.suffix.casefold() == ".py":
        return [sys.executable, str(launcher)], root
    return [str(launcher)], launcher.parent
