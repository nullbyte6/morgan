"""Daily Markdown conversation logs shared by all sessions."""

from .identity import get_assistant


import re
from datetime import datetime
from pathlib import Path


from .config import HOME_PATH, ensure_storage
from .output import markdown_text


SESSION_NAME = re.compile(r"\d{4}-\d{2}-\d{2}\.md")
SESSION_HEADER = "###"
MAX_DAYS = 24
_current_session_path: Path | None = None


def open_current_session_log() -> str:
    """Open this the assistant process's current session log in the default application."""
    from .brain import open_file

    if _current_session_path is None:
        return "Error: no session log is active"
    return open_file(str(_current_session_path))


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
        elif action not in "status":
            return "Uso: /private [on|off|status]"
        return ("Private Mode, on"
                if self.private else
                "Private Mode, off")

    def _start_day(self, started):
        self.path = self.directory / f"{started:%Y-%m-%d}.md"
        try:
            log = self.path.open("x", encoding="utf-8")
        except FileExistsError:
            pass
        else:
            with log:
                log.write(f"{SESSION_HEADER} {get_assistant().name} Log — {started:%Y-%m-%d}")
        self._prune()
        global _current_session_path
        _current_session_path = self.path

    def _prune(self):
        logs = []
        for path in self.directory.iterdir():
            if (SESSION_NAME.fullmatch(path.name) and not path.is_symlink()
                    and path.is_file()):
                with path.open(encoding="utf-8") as log:
                    if log.read(256).lstrip().startswith(SESSION_HEADER):
                        logs.append(path)
        oldest = sorted((path for path in logs if path != self.path),
                        key=lambda path: path.name)
        for path in oldest[:max(0, len(logs) - MAX_DAYS)]:
            if path.resolve().parent != self.directory:
                raise OSError("Session log resolved outside the log directory")
            path.unlink()

    def write(self, role, text):
        """Append Markdown with intact code fences, newlines and indentation."""
        if self.private:
            return
        text = markdown_text(text) if text else ""
        if not text.strip():
            return
        role = " ".join(str(role).splitlines()).strip()
        now = datetime.now().astimezone()
        if self.path.name != f"{now:%Y-%m-%d}.md":
            self._start_day(now)
        with self.path.open("a", encoding="utf-8") as log:
            log.write(f"\n\n[{now:%H:%M:%S %z}] \n{role}: {text}")
