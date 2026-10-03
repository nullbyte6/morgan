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
"""Direct shell commands typed after > run here, without involving the model."""
import codecs
import re
import subprocess
import threading
from src.platforms import current_platform

MAX_OUTPUT = 64 * 1024
_CHANGE_DIRECTORY = re.compile(r"cd(?:\s+.*)?", re.IGNORECASE | re.DOTALL)


def shell_command_text(text: str) -> str | None:
    """The command after a leading >, or None when the text is not a shell command."""
    if not text.startswith(">"):
        return None
    command = text[1:]
    return command[1:] if command.startswith(" ") else command


def is_change_directory(command: str) -> bool:
    return _CHANGE_DIRECTORY.fullmatch(command.strip()) is not None


class ShellRun:
    """One command with streamed, bounded output and a cancellable process tree."""

    def __init__(self, command: str, directory: str, on_output, on_done):
        self.command = command
        self.directory = directory
        self.on_output = on_output
        self.on_done = on_done
        self.output = ""
        self.process = None
        self.cancelled = False
        self.exit_code = None
        self.error = ""

    def start(self):
        from src.init.commands import _shell_command

        try:
            argv = _shell_command(self.command, current_platform().default_shell())
            self.process = subprocess.Popen(
                argv, cwd=self.directory, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0,
                creationflags=current_platform().no_window_flags)
        except (OSError, ValueError) as error:
            self.error = str(error)
            self.on_done(self)
            return
        threading.Thread(target=self._read, name="tui-shell", daemon=True).start()

    def _read(self):
        decoder = codecs.getincrementaldecoder(current_platform().console_encoding())(errors="replace")
        stream = self.process.stdout
        try:
            while True:
                data = stream.read(4096)
                if not data:
                    break
                self.output = (self.output + decoder.decode(data).replace("\r\n", "\n"))[-MAX_OUTPUT:]
                self.on_output(self)
            self.exit_code = self.process.wait()
        except OSError as error:
            self.error = str(error)
        finally:
            stream.close()
            self.on_done(self)

    def cancel(self):
        process = self.process
        if process is None or process.poll() is not None:
            return
        self.cancelled = True
        try:
            import psutil

            parent = psutil.Process(process.pid)
            for child in parent.children(recursive=True):
                child.kill()
            parent.kill()
        except Exception:
            process.kill()
