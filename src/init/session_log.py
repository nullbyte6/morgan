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
"""Daily Markdown conversation logs shared by all sessions."""

import re
import uuid
from datetime import datetime
from pathlib import Path

from .config import HOME_PATH, ensure_storage
from .identity import get_assistant
from .lang import tr
from .output import markdown_text

SESSION_NAME = re.compile(r"\d{4}-\d{2}-\d{2}\.md")
session_header = ""
MAX_DAYS = 24
_current_session_path: Path | None = None


def open_current_session_log() -> str:
    """Open this the assistant process's current session log in the default application."""
    from .brain import open_file

    if _current_session_path is None:
        return tr("session.none")
    return open_file(str(_current_session_path))


CODE_FENCE = re.compile(
    r"(?P<indent>^[ \t]{0,3})(?P<fence>`{3,})[ \t]*"
    r"(?P<language>[A-Za-z0-9_+#.-]+)[^\n]*\n"
    r"(?P<code>.*?)"
    r"^[ \t]{0,3}(?P<closing>`{3,})[ \t]*(?:\n|$)",
    re.MULTILINE | re.DOTALL,
)

CODE_EXTENSIONS = {
    "python": ".py",
    "py": ".py",
    "javascript": ".js",
    "js": ".js",
    "typescript": ".ts",
    "ts": ".ts",
    "json": ".json",
    "html": ".html",
    "css": ".css",
    "bash": ".sh",
    "shell": ".sh",
    "sh": ".sh",
    "powershell": ".ps1",
    "ps1": ".ps1",
    "batch": ".bat",
    "bat": ".bat",
    "cmd": ".cmd",
    "c": ".c",
    "cpp": ".cpp",
    "c++": ".cpp",
    "h": ".h",
    "hpp": ".hpp",
    "java": ".java",
    "rust": ".rs",
    "rs": ".rs",
    "sql": ".sql",
    "yaml": ".yaml",
    "yml": ".yml",
    "xml": ".xml",
    "toml": ".toml",
}

def extract_code(text: str, log_path: Path) -> str:
    """Archive fenced code blocks and replace them with Markdown links."""
    if not text or "```" not in text:
        return text

    code_dir = log_path.parent / log_path.stem
    counter = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal counter

        if len(match.group("closing")) < len(match.group("fence")):
            return match.group(0)

        language = match.group("language").casefold()
        extension = CODE_EXTENSIONS.get(language)

        if extension is None:
            return match.group(0)

        code = match.group("code")

        if not code.strip():
            return match.group(0)

        counter += 1
        filename = f"{counter:02d}-{uuid.uuid4().hex[:8]}{extension}"
        destination = code_dir / filename

        try:
            code_dir.mkdir(parents=True, exist_ok=True)
            with destination.open("x", encoding="utf-8", newline="\n") as file:
                file.write(code)

        except OSError:
            return match.group(0)

        relative_path = f"{log_path.stem}/{filename}"
        return f"**({language}):** [{filename}]({relative_path})\n"

    return CODE_FENCE.sub(replace, text)


class SessionLog:
    def __init__(self, directory=None):
        self.private = False
        if directory is None:
            ensure_storage()
        self.directory = (Path(directory) if directory is not None
                          else HOME_PATH / ".log").resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self._start_day(datetime.now().astimezone())

    def handle_command(self, command):
        """Handle local privacy controls before recording or sending input."""
        parts = command.strip().casefold().split()
        if not parts or parts[0] not in ("/private", "/private"):
            return None
        action = parts[1] if len(parts) == 2 else "toggle" if len(parts) == 1 else ""
        if action == "toggle":
            self.private = not self.private
        elif action in ("on", "off"):
            self.private = action == "on"
        elif action != "status":
            return tr("privacy.usage")
        return tr("privacy.on" if self.private else "privacy.off")

    def _start_day(self, started):
        self.path = self.directory / f"{started:%Y-%m-%d}.md"
        try:
            log = self.path.open("x", encoding="utf-8")
        except FileExistsError:
            pass
        else:
            with log:
                session_header = f"{get_assistant().name} Log — {started:%Y-%m-%d}"
                log.write(session_header)
        self._prune()
        global _current_session_path
        _current_session_path = self.path

    def _prune(self):
        logs = []
        for path in self.directory.iterdir():
            if (SESSION_NAME.fullmatch(path.name) and not path.is_symlink()
                    and path.is_file()):
                with path.open(encoding="utf-8") as log:
                    if log.read(256).lstrip().startswith(session_header):
                        logs.append(path)
        oldest = sorted((path for path in logs if path != self.path),
                        key=lambda path: path.name)
        for path in oldest[:max(0, len(logs) - MAX_DAYS)]:
            if path.resolve().parent != self.directory:
                raise OSError(tr('session_log.session_log_resolved_outside_the_log_directory'))
            path.unlink()

    def write(self, role, text):
        """Append Markdown, archiving supported fenced code blocks."""
        if self.private:
            return

        text = markdown_text(text) if text else ""
        if not text.strip():
            return

        role = " ".join(str(role).splitlines()).strip()
        now = datetime.now().astimezone()
        if self.path.name != f"{now:%Y-%m-%d}.md":
            self._start_day(now)

        text = extract_code(text, self.path)
        with self.path.open("a", encoding="utf-8") as log:
            log.write(f"\n\n[{now:%H:%M:%S %z}] \n{role}: {text}")

