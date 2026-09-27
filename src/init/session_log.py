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

import copy
import json
import logging
import re
import uuid
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .config import HOME_PATH, ensure_storage
from .identity import get_assistant
from .lang import tr
from .output import markdown_text

SESSION_NAME = re.compile(r"\d{4}-\d{2}-\d{2}\.md")
MAX_DAYS = 24
_current_session_path: Path | None = None
_log_lock = threading.RLock()


def open_current_session_log() -> str:
    """Open this the assistant process's current session log in the default application."""
    from .brain import open_file

    from .sessions import active_execution
    identity = active_execution.get()
    path = identity.session.log.path if identity is not None else _current_session_path
    if path is None:
        return tr("session.none")
    return open_file(str(path))


TOOL_ARTIFACT_MIN_BYTES = 4096


def message_status(lifecycle):
    """Translate task lifecycle to the independent conversation persistence domain."""
    status = str(lifecycle)
    if status in {"complete", "completed"}:
        return "completed"
    if status in {"active", "waiting", "blocked", "interrupted", "cancelled"}:
        return "interrupted"
    if status in {"limit_reached", "failed", "error"}:
        return "error"
    raise ValueError(f"Unknown conversation lifecycle: {status}")


class SessionContext:
    """Conversation state and external artifacts for one live session."""

    def __init__(self, session_id: str, directory: Path):
        self.session_id = session_id
        self.messages = []
        self.directory = Path(directory).resolve() / "artifacts" / session_id

    def add_exchange(self, prompt: str, reply: str):
        from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
        self.messages.extend((ModelRequest(parts=[UserPromptPart(prompt)]),
                              ModelResponse(parts=[TextPart(reply)])))

    def _store(self, content: str, extension: str, label: str) -> str:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{uuid.uuid4().hex}{extension}"
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        return f"[{label}]({path.as_posix()})"

    def externalize_messages(self, messages):
        from pydantic_ai.messages import ToolReturnPart
        result = copy.deepcopy(list(messages))
        for message in result:
            for part in message.parts:
                if isinstance(part, ToolReturnPart):
                    if isinstance(part.content, str):
                        raw = part.content
                    else:
                        raw = json.dumps(part.content, ensure_ascii=False, indent=2,
                                         default=str)
                    if len(raw.encode("utf-8")) >= TOOL_ARTIFACT_MIN_BYTES:
                        extension = ".json" if raw.lstrip().startswith(("{", "[")) else ".txt"
                        part.content = self._store(
                            raw, extension, f"Tool result: {part.tool_name}")
        return result


class SessionLog:
    def __init__(self, directory=None, *, memory_service=None, session_id=None):
        self.private = False
        self.session_id = session_id or uuid.uuid4().hex
        context_directory = Path(directory) if directory is not None else HOME_PATH / ".log"
        self.context = SessionContext(self.session_id, context_directory)
        self.started_at = datetime.now().astimezone().isoformat()
        self.last_user_message_id = None
        self.last_user_text = ""
        self.memory_error = None
        self._memory_service = memory_service
        self._use_configured_memory = directory is None
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
        with _log_lock:
            self.path = self.directory / f"{started:%Y-%m-%d}.md"
            try:
                log = self.path.open("x", encoding="utf-8")
            except FileExistsError:
                pass
            else:
                with log:
                    log.write(f"{get_assistant().name} Log — {started:%Y-%m-%d}")
            self._prune()
            global _current_session_path
            _current_session_path = self.path

    def _prune(self):
        logs = []
        header = f"{get_assistant().name} Log —"
        for path in self.directory.iterdir():
            if (SESSION_NAME.fullmatch(path.name) and not path.is_symlink()
                    and path.is_file()):
                with path.open(encoding="utf-8") as log:
                    if log.read(256).lstrip().startswith(header):
                        logs.append(path)
        oldest = sorted((path for path in logs if path != self.path),
                        key=lambda path: path.name)
        for path in oldest[:max(0, len(logs) - MAX_DAYS)]:
            if path.resolve().parent != self.directory:
                raise OSError(tr('session_log.session_log_resolved_outside_the_log_directory'))
            path.unlink()

    def write(self, role, text, *, status="completed"):
        """Append Markdown while retaining fenced code in the conversation."""
        if self.private:
            return

        status = message_status(status)
        text = markdown_text(text) if text else ""
        if not text.strip():
            return

        role = " ".join(str(role).splitlines()).strip()
        now = datetime.now().astimezone()
        if self.path.name != f"{now:%Y-%m-%d}.md":
            self._start_day(now)

        original = text
        with _log_lock, self.path.open("a", encoding="utf-8") as log:
            log.write("\n\n")
            source_ref = str(self.path) + "#byte=" + str(log.tell())
            log.write(f"[{now:%H:%M:%S %z}] [session:{self.session_id}] \n{role}: {text}")
        assistant = get_assistant()
        canonical_role = ("assistant" if role == assistant.name else
                          "system" if role == "System" else "user")
        if canonical_role == "user":
            self.last_user_text = original
            self.last_user_message_id = None
        try:
            service = self._get_memory_service()
            if service is None:
                return
            if self._use_configured_memory:
                from .config import load_config
                if not load_config()["memory"]["store_history"]:
                    return
            service.start_session(session_id=self.session_id, started_at=self.started_at,
                                  metadata={"log_directory": str(self.directory)})
            message_id = service.record_message(self.session_id, canonical_role, original,
                                                created_at=now.isoformat(), status=status,
                                                source_ref=source_ref)
            if canonical_role == "user":
                self.last_user_message_id = message_id
            self.memory_error = None
        except Exception as error:
            self.memory_error = str(error)
            logging.getLogger("assistant.memory").exception("Conversation retained in Markdown; database persistence failed")

    def _get_memory_service(self):
        if self._use_configured_memory:
            from .memory.integration import configured_service
            return configured_service()
        return self._memory_service

    @contextmanager
    def memory_scope(self):
        from .memory.integration import MemoryTurn, active_memory
        service = None
        if not self.private:
            try:
                service = self._get_memory_service()
            except Exception as error:
                self.memory_error = str(error)
                logging.getLogger("assistant.memory").exception("Memory tools unavailable")
        token = active_memory.set(MemoryTurn(service, self.session_id,
                                            self.last_user_message_id, self.last_user_text,
                                            self.private, self.memory_error))
        try:
            yield
        finally:
            active_memory.reset(token)

    def close(self):
        try:
            service = self._get_memory_service()
            if service is not None:
                service.end_session(self.session_id)
        except Exception as error:
            self.memory_error = str(error)
            logging.getLogger("assistant.memory").exception("Memory session could not be closed")

