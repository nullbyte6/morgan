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
from __future__ import annotations
from src.init.lang import tr
from .identity import get_assistant_identifier, get_assistant_environment
import logging
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import shutil


class LogStream:
    """File-like stream that redirects stdout/stderr into logging."""
    def __init__(self, logger_name: str, level: int):
        self.logger = logging.getLogger(logger_name)
        self.level = level
        self._buffer = ""

    def write(self, text):
        if not text:
            return 0

        text = text.replace("\r", "\n")
        self._buffer += text

        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.rstrip("\r")

            if line.strip():
                self.logger.log(self.level, line)

        return len(text)

    def flush(self):
        if self._buffer.strip():
            self.logger.log(
                self.level,
                self._buffer.rstrip("\r"))
        self._buffer = ""

    def isatty(self):
        return False

    @property
    def encoding(self):
        return "utf-8"


# noinspection PyBroadException
class DebugConsole:
    def __init__(self, name: str | None = None):
        log_dir = Path(tempfile.gettempdir()) / get_assistant_identifier()
        log_dir.mkdir(parents=True, exist_ok=True)

        self.log_path = log_dir / "agent.log"
        self.console_script = log_dir / "console.ps1"

        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr

        self._original_fd1 = None
        self._original_fd2 = None
        self._native_threads = []
        self._native_read_fds = []

    def start(self):
        self.log_path.touch(exist_ok=True)

        if get_assistant_environment("EXTERNAL_CONSOLE") == "1":
            return

        log_path = str(self.log_path).replace("'", "''")
        title = tr("console.console_title")
        script_title = title.replace("'", "''")
        self.console_script.write_text(
            f"$Host.UI.RawUI.WindowTitle = '{script_title}'\n"
            f"Get-Content -LiteralPath '{log_path}' -Tail 30 -Wait\n",
            encoding="utf-8")

        pwsh = shutil.which("pwsh.exe")
        wt = shutil.which("wt.exe")

        if not pwsh:
            raise FileNotFoundError(tr("console.error_pwsh_not_found"))

        if not wt:
            raise FileNotFoundError(tr("console.error_wt_not_found"))

        command = [
            wt,
            "-w", "new",
            "new-tab",
            "--title", title,
            "--",
            pwsh,
            "-NoLogo",
            "-NoProfile",
            "-NoExit",
            "-File", str(self.console_script),
        ]

        subprocess.Popen(
            command,
            cwd=str(self.console_script.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)

    def configure_logging(self):
        handler = logging.FileHandler(
            self.log_path,
            encoding="utf-8",
        )

        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)-8s | "
                "%(name)s | %(message)s",
                datefmt="%H:%M:%S",
            )
        )

        root = logging.getLogger()
        root.handlers.clear()
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)

    def redirect_streams(self):
        sys.stdout = LogStream("assistant.stdout", logging.INFO)
        sys.stderr = LogStream("assistant.stderr", logging.INFO)

    def restore_streams(self):
        sys.stdout = self.original_stdout
        sys.stderr = self.original_stderr

    def print_to_ui(self, *args, **kwargs):
        print(*args, file=self.original_stdout, **kwargs,)

    def _pipe_native_stream(self, fd: int, logger_name: str):
        read_fd, write_fd = os.pipe()

        original_fd = os.dup(fd)
        os.dup2(write_fd, fd)
        os.close(write_fd)

        logger = logging.getLogger(logger_name)

        def reader():
            with os.fdopen(
                    read_fd,
                    "r",
                    encoding="utf-8",
                    errors="replace",
                    buffering=1) as pipe:
                for line in pipe:
                    line = line.rstrip("\r\n")
                    if line.strip():
                        logger.info(line)

        thread = threading.Thread(
            target=reader,
            name=f"{logger_name}-reader",
            daemon=True)
        thread.start()

        self._native_threads.append(thread)
        return original_fd

    def redirect_native_streams(self):
        if self._original_fd1 is not None:
            return

        try:
            sys.stdout.flush()
        except Exception:
            pass

        try:
            sys.stderr.flush()
        except Exception:
            pass

        self._original_fd1 = self._pipe_native_stream(1,"assistant.native.stdout")
        self._original_fd2 = self._pipe_native_stream(2, "assistant.native.stderr")

    def restore_native_streams(self):
        if self._original_fd1 is not None:
            try:
                os.dup2(self._original_fd1, 1)
            finally:
                os.close(self._original_fd1)
                self._original_fd1 = None

        if self._original_fd2 is not None:
            try:
                os.dup2(self._original_fd2, 2)
            finally:
                os.close(self._original_fd2)
                self._original_fd2 = None
