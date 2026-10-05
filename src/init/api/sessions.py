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
"""Conversation sessions owned by phone clients, each running on its own worker thread."""
import asyncio
import dataclasses
import itertools
import json
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from src.init.hot_reload import is_reload_command
from src.init.session_runner import SessionRunner

MAX_SESSIONS = 4
MAX_MESSAGE_CHARACTERS = 8000
MAX_TRANSCRIPT = 200
SUBSCRIBER_BACKLOG = 2000

log = logging.getLogger("assistant.api")


class SessionLimitReached(Exception):
    pass


class SessionBusy(Exception):
    pass


class InvalidMessage(ValueError):
    pass


class ApiSessionRunner(SessionRunner):
    """A session that never speaks on the PC and never takes over its microphone."""
    report_git_diff = False

    def __init__(self, session_key):
        super().__init__(False, muted=True, session_key=session_key, primary=False)

    def claim_speech(self):
        return False

    def ask(self, turn_id, message):
        from src.init import brain
        brain.set_working_directory_owner(self.session.context)
        try:
            self._ask(turn_id, message, None)
        except Exception as error:
            self.rejected.emit(turn_id, str(error))
        finally:
            self.speech_owner = False
            self.assistant.release_speech(self)


def _plain(value):
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _plain(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class ApiSession:
    """Thread-safe bridge from one SessionRunner's signals to asyncio subscribers."""

    def __init__(self, allow_remote_confirmation: bool):
        self.id = uuid.uuid4().hex[:12]
        self.created_at = int(time.time())
        self.allow_remote_confirmation = allow_remote_confirmation
        self.runner = ApiSessionRunner(self.id)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="api-" + self.id)
        self.lock = threading.Lock()
        self.subscribers = []
        self.transcript = []
        self.turns = itertools.count(1)
        self.ready = False
        self.error = ""
        self.busy = False
        self.turn = 0
        self.partial = ""
        self.pending_confirmation = None
        self.closed = False
        self._connect()
        self.executor.submit(self.runner.initialize)

    def _connect(self):
        runner = self.runner
        runner.ready.connect(self._on_ready)
        runner.failed.connect(self._on_failed)
        runner.accepted.connect(lambda turn: self._emit("accepted", turn=turn))
        runner.rejected.connect(self._on_rejected)
        runner.chunk.connect(self._on_chunk)
        runner.phase.connect(self._on_phase)
        runner.activity.connect(lambda turn, activity: self._emit(
            "activity", turn=turn, activity=_plain(activity)))
        runner.task_title.connect(lambda turn, title: self._emit(
            "task_title", turn=turn, title=title))
        runner.finished.connect(self._on_finished)
        runner.permission_denied.connect(lambda turn: self._emit("permission_denied", turn=turn))
        runner.confirmation_requested.connect(self._on_confirmation_requested)
        runner.confirmation_closed.connect(self._on_confirmation_closed)

    def _emit(self, event_type, mutate=None, /, **fields):
        event = {"type": event_type, **fields}
        with self.lock:
            if mutate is not None:
                mutate()
            subscribers = list(self.subscribers)
        for queue, loop in subscribers:
            try:
                loop.call_soon_threadsafe(self._deliver, queue, event)
            except RuntimeError:
                self.unsubscribe(queue)

    @staticmethod
    def _deliver(queue, event):
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            while not queue.empty():
                queue.get_nowait()
            queue.put_nowait({"type": "resync"})

    def _record(self, role, text, **extra):
        self.transcript.append({"role": role, "text": text, "time": int(time.time()), **extra})
        del self.transcript[:-MAX_TRANSCRIPT]

    def _finish_turn(self):
        self.busy = False
        self.partial = ""
        self.pending_confirmation = None

    def _on_ready(self):
        def mutate():
            self.ready = True
        self._emit("ready", mutate)

    def _on_failed(self, error):
        def mutate():
            if not self.ready:
                self.error = error
            self._finish_turn()
            self._record("system", error, status="error")
        log.warning("Session %s failed: %s", self.id, error)
        self._emit("failed", mutate, error=error)

    def _on_rejected(self, turn, error):
        def mutate():
            self._finish_turn()
            self._record("system", error, status="error")
        self._emit("rejected", mutate, turn=turn, error=error)

    def _on_chunk(self, turn, chunk):
        def mutate():
            self.partial += chunk
        self._emit("chunk", mutate, turn=turn, text=chunk)

    def _on_phase(self, turn, phase):
        if phase.startswith("step:"):
            try:
                step = json.loads(phase[5:])
            except ValueError:
                step = {}
            if isinstance(step, dict):
                self._emit("step", turn=turn, **{key: step.get(key, "")
                                                 for key in ("kind", "tool", "subject")})
                return
        self._emit("phase", turn=turn, phase=phase)

    def _on_finished(self, reply):
        def mutate():
            if reply:
                self._record("assistant", reply, turn=self.turn)
            self._finish_turn()
        self._emit("finished", mutate, turn=self.turn, reply=reply)

    def _on_confirmation_requested(self, turn, message, request_id, timeout):
        if not self.allow_remote_confirmation:
            self.runner.resolve_confirmation(False, request_id)
            self._emit("confirmation_blocked", turn=turn, message=message)
            return

        def mutate():
            self.pending_confirmation = {"id": request_id, "message": message,
                                         "timeout": timeout, "turn": turn}
        self._emit("confirmation", mutate, **{"turn": turn, "id": request_id,
                                              "message": message, "timeout": timeout})

    def _on_confirmation_closed(self, request_id):
        def mutate():
            pending = self.pending_confirmation
            if pending is not None and pending["id"] == request_id:
                self.pending_confirmation = None
        self._emit("confirmation_closed", mutate, id=request_id)

    def summary(self) -> dict:
        with self.lock:
            return {"id": self.id, "created_at": self.created_at, "ready": self.ready,
                    "busy": self.busy, "error": self.error}

    def subscribe(self, queue, loop) -> dict:
        with self.lock:
            self.subscribers.append((queue, loop))
            return {"type": "snapshot",
                    "session": {"id": self.id, "created_at": self.created_at,
                                "ready": self.ready, "busy": self.busy, "error": self.error},
                    "turn": self.turn, "partial": self.partial,
                    "confirmation": self.pending_confirmation,
                    "transcript": list(self.transcript)}

    def unsubscribe(self, queue):
        with self.lock:
            self.subscribers = [item for item in self.subscribers if item[0] is not queue]

    def send(self, text: str) -> int:
        text = str(text).strip()
        if not text:
            raise InvalidMessage("The message is empty")
        if len(text) > MAX_MESSAGE_CHARACTERS:
            raise InvalidMessage(f"The message exceeds {MAX_MESSAGE_CHARACTERS} characters")
        if is_reload_command(text):
            raise InvalidMessage("Reload commands are only available on the PC")
        with self.lock:
            if self.closed:
                raise SessionBusy("The session is closed")
            if self.busy:
                raise SessionBusy("The session is still answering")
            self.busy = True
            self.partial = ""
            self.runner.cancel_event = threading.Event()
            self.turn = next(self.turns)
            turn = self.turn
            self._record("user", text, turn=turn)
        self.executor.submit(self.runner.ask, turn, text)
        return turn

    def interrupt(self):
        self.runner.interrupt()

    def confirm(self, request_id: int, accepted: bool) -> bool:
        if not self.allow_remote_confirmation:
            return False
        return self.runner.resolve_confirmation(bool(accepted), request_id)

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
        self._emit("closed")
        self.runner.interrupt()
        self.executor.submit(self.runner.shutdown)
        self.executor.shutdown(wait=False)


class SessionManager:
    def __init__(self, allow_remote_confirmation: bool = False):
        self.allow_remote_confirmation = allow_remote_confirmation
        self._sessions = {}
        self._lock = threading.Lock()

    def create(self) -> ApiSession:
        with self._lock:
            if len(self._sessions) >= MAX_SESSIONS:
                raise SessionLimitReached(f"At most {MAX_SESSIONS} sessions can be open")
            session = ApiSession(self.allow_remote_confirmation)
            self._sessions[session.id] = session
            return session

    def get(self, session_id: str) -> ApiSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def list(self) -> list[dict]:
        with self._lock:
            sessions = list(self._sessions.values())
        return [session.summary() for session in sessions]

    def close(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        session.close()
        return True

    def close_all(self):
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.close()
