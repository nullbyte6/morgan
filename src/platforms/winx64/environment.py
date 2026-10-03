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
"""Per-user environment, file locks, directory junctions, elevation and shells on Windows."""

import ctypes
import os
import shutil


def user_environment(name):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            return str(winreg.QueryValueEx(key, name)[0])
    except OSError:
        return None


def set_user_environment(name, value):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def lock_file(file, blocking=True):
    import msvcrt
    msvcrt.locking(file.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)


def unlock_file(file):
    import msvcrt
    msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)


def remove_link(path):
    os.rmdir(path)


def is_elevated():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def default_shell():
    return "pwsh" if shutil.which("pwsh") else "powershell"


def elevation_prefix(cwd):
    from src.init.lang import tr
    sudo = shutil.which("sudo.exe")
    if not sudo:
        raise ValueError(tr("command.sudo_unavailable"))
    return [sudo, "--chdir", cwd, "--"]
