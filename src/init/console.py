from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path


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


class DebugConsole:
    def __init__(self, name: str = "Arlo"):
        log_dir = Path(tempfile.gettempdir()) / "arlo"
        log_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.log_path = log_dir / f"{timestamp}.log"
        self.console_script = log_dir / f"{timestamp}-console.ps1"
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr

    def start(self):
        self.log_path.touch()
        self.console_script.write_text(("$Host.UI.RawUI.WindowTitle = 'ARLO Console'\n"
                f"Get-Content -Path '{self.log_path}' -Wait\n"),encoding="utf-8")

        subprocess.Popen(
            [
                "sudo",
                "cmd.exe",
                "/c",
                "start",
                "",
                "wt.exe",
                "-w",
                "new",
                "new-tab",
                "--title",
                "ARLO Console",
                "--suppressApplicationTitle",
                "pwsh.exe",
                "-NoLogo",
                "-NoProfile",
                "-NoExit",
                "-File",
                str(self.console_script),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

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
        sys.stdout = LogStream("arlo.stdout", logging.INFO)
        sys.stderr = LogStream("arlo.stderr", logging.INFO)

    def restore_streams(self):
        sys.stdout = self.original_stdout
        sys.stderr = self.original_stderr

    def print_to_ui(self, *args, **kwargs):
        print(*args, file=self.original_stdout, **kwargs,)