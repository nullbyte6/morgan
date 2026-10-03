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
"""PowerShell in a ConPTY pseudo-terminal and the console code page on Windows."""

import base64
import os
from pathlib import Path
import shutil
import subprocess
import sys


class WinTerminal:
    def __init__(self, argv, directory, environment, columns, rows):
        from winpty import PTY
        self.process = PTY(columns, rows, timeout=3000)
        if argv is None:
            shell = shutil.which("pwsh.exe") or str(
                Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
                / "PowerShell" / "7" / "pwsh.exe")
            if not Path(shell).is_file():
                shell = shutil.which("powershell.exe")
            if shell is None:
                raise FileNotFoundError("PowerShell is unavailable")
            argv = [shell, "-NoLogo", "-NoProfile"]
        if getattr(sys, "frozen", False):
            executable, arguments = argv[0], argv[1:]
        else:
            python = Path(sys.executable)
            if python.name.lower() == "pythonw.exe":
                python = python.with_name("python.exe")
            bootstrap = Path(__file__).with_name("terminal_shell.py")
            executable, arguments = str(python), [str(bootstrap), *argv]
        self.process.spawn(executable,
                           cmdline=" " + subprocess.list2cmdline(arguments),
                           cwd=str(directory),
                           env="\0".join(f"{k}={v}" for k, v in environment.items()) + "\0")
        self.pid = self.process.pid

    def write(self, text):
        self.process.write(text)

    def resize(self, columns, rows):
        self.process.set_size(columns, rows)

    def read(self):
        return self.process.read(blocking=False)

    def isalive(self):
        return self.process.isalive()

    def exit_status(self):
        return self.process.get_exitstatus()

    def kill(self):
        subprocess.run(
            ["taskkill.exe", "/PID", str(self.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)

    def close(self):
        pass


def terminal_command_line(command):
    encoded = base64.b64encode(command.encode("utf-8")).decode("ascii")
    return ". ([scriptblock]::Create([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + encoded + "'))))"


def console_encoding():
    try:
        import ctypes
        code_page = ctypes.windll.kernel32.GetConsoleOutputCP()
        if code_page:
            return f"cp{code_page}"
    except (AttributeError, OSError):
        pass
    return "utf-8"
