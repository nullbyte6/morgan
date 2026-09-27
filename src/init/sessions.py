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
"""Conversation ownership and the application's bounded session registry."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
import threading
import uuid


@dataclass(frozen=True)
class ExecutionIdentity:
    session: object
    turn_id: int

    @property
    def session_id(self):
        return self.session.session_id


active_execution = ContextVar("arlo_execution", default=None)


def execution_identity():
    identity = active_execution.get()
    if identity is None:
        raise RuntimeError("This operation requires an Arlo session")
    return identity


@contextmanager
def session_scope(session, turn_id=0):
    token = active_execution.set(ExecutionIdentity(session, turn_id))
    try:
        yield
    finally:
        active_execution.reset(token)


@dataclass(eq=False)
class ArloSession:
    backend: object
    manager: object
    working_directory: Path
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    turn_id: int = 0
    closing: bool = False
    closed: bool = False
    show_working_directory: bool = False
    log: object = None
    assistant: object = None
    worker: object = None
    thread: object = None
    workspace: object = None
    panel_id: str | None = None
    tool_state: dict = field(default_factory=dict)
    pending_requests: set = field(default_factory=set)

    def accepts(self, session_id, turn_id):
        return (not self.closing and not self.closed and session_id == self.session_id
                and turn_id == self.turn_id)

    def tools(self, name, factory=dict):
        if name not in self.tool_state:
            self.tool_state[name] = factory()
        return self.tool_state[name]


class SessionManager:
    LIMIT = 4

    def __init__(self, backend, *, directory=None):
        self.backend = backend
        self.directory = Path(directory or Path.home()).resolve()
        self.sessions = {}
        self.focused_session = None
        self.desktop_session = None
        self.voice_owner = None
        self.shutdown_requested = threading.Event()
        self._lock = threading.RLock()
        self._reload_lock = threading.RLock()
        self._executing = set()

    @property
    def name(self):
        from .identity import get_assistant_name
        return get_assistant_name()

    def create(self):
        with self._lock:
            if len(self.sessions) >= self.LIMIT or self.shutdown_requested.is_set():
                return None
            session = ArloSession(self.backend, self, self.directory)
            self.sessions[session.session_id] = session
            return session

    def get(self, session_id):
        with self._lock:
            return self.sessions.get(session_id)

    def focus(self, session):
        with self._lock:
            if session is not None and self.get(session.session_id) is session and not session.closing:
                self.focused_session = session

    def project(self, session):
        with self._lock:
            if session is not None and (self.get(session.session_id) is not session or session.closing):
                return False
            self.desktop_session = session
            return True

    def acquire_voice(self, session):
        with self._lock:
            if session.closing or session.closed or self.get(session.session_id) is not session:
                return False
            if self.voice_owner not in (None, session):
                return False
            self.voice_owner = session
            return True

    def release_voice(self, session):
        with self._lock:
            if self.voice_owner is session:
                self.voice_owner = None

    def begin_close(self, session):
        with self._lock:
            if self.get(session.session_id) is not session or session.closing:
                return False
            session.closing = True
            if self.focused_session is session:
                self.focused_session = None
            if self.desktop_session is session:
                self.desktop_session = None
            return True

    def complete_close(self, session):
        with self._lock:
            if not session.closing or session.session_id in self._executing:
                return False
            if session.thread is not None and session.thread.isRunning():
                return False
            if session.pending_requests:
                return False
            if session.workspace is not None and session.workspace.voice_thread is not None:
                return False
            self.release_voice(session)
            session.closed = True
            self.sessions.pop(session.session_id, None)
            return True

    @contextmanager
    def execution(self, session, turn_id):
        with self._reload_lock:
            if session.closing or session.closed:
                raise InterruptedError("Session is closing")
            self._executing.add(session.session_id)
        try:
            with session_scope(session, turn_id):
                yield
        finally:
            with self._reload_lock:
                self._executing.discard(session.session_id)

    def reload(self, operation, session):
        with self._reload_lock:
            if self._executing - {session.session_id}:
                return "Reload is unavailable while another session is executing; retry when it is idle."
            return operation()
