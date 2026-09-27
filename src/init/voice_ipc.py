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
"""Local durable wake inbox and crash-safe audio ownership (no network
listener)."""
from __future__ import annotations

import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from .config import HOME_PATH
from .identity import get_assistant_identifier


WAKE_RECORD_REQUEST = f"{get_assistant_identifier()}://voice/start-recording"


def voice_directory() -> Path:
    path = HOME_PATH / "voice"
    path.mkdir(parents=True, exist_ok=True)
    return path


class ProcessLock:
    """OS file lock; automatically released even if the owning process dies."""

    def __init__(self, name: str, directory: Path | None = None):
        self.path = (directory or voice_directory()) / (name + ".lock")
        self.file = None

    def acquire(self) -> bool:
        if self.file is not None:
            return True
        file = self.path.open("a+b")
        try:
            file.seek(0, os.SEEK_END)
            if not file.tell():
                file.write(b"\0")
                file.flush()
            file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            file.close()
            return False
        self.file = file
        return True

    def release(self):
        if self.file is not None:
            self.file.close()
            self.file = None


def audio_requested(directory: Path | None = None) -> bool:
    lock = ProcessLock("desktop-audio", directory)
    if not lock.acquire():
        return True
    lock.release()
    return False


@contextmanager
def desktop_audio(*, stop_event=None, timeout=5.0, tail=0.6, directory=None):
    """Ask wake capture to yield, then own input/playback for the entire turn.
    Only worker threads wait here. The wake thread checks the priority lock on
    every audio block, closes its stream, then releases the microphone lock.
    """
    priority = ProcessLock("desktop-audio", directory)
    microphone = ProcessLock("microphone", directory)
    deadline = time.monotonic() + timeout
    acquired = False

    class AudioLease:
        def yield_to_wake_listener(self):
            nonlocal acquired
            if acquired:
                microphone.release()
                priority.release()
                acquired = False

        def reclaim(self):
            nonlocal acquired, deadline
            if acquired:
                return
            deadline = time.monotonic() + timeout
            for lock in (priority, microphone):
                while not lock.acquire():
                    if stop_event is not None and stop_event.is_set():
                        raise InterruptedError("Audio request cancelled")
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Microphone is busy; please try again")
                    time.sleep(0.025)
            acquired = True

    try:
        for lock in (priority, microphone):
            while not lock.acquire():
                if stop_event is not None and stop_event.is_set():
                    raise InterruptedError("Audio request cancelled")
                if time.monotonic() >= deadline:
                    raise TimeoutError("Microphone is busy; please try again")
                time.sleep(0.025)
        acquired = True
        yield AudioLease()
    finally:
        # Let speaker/reverb tails settle before wake capture resumes.
        if acquired and tail:
            time.sleep(tail)
        microphone.release()
        priority.release()


class WakeInbox:
    """SQLite transactions survive startup/restarts and deduplicate UUIDs.

    Dispatch is at-most-once: a crash after claim must never replay a possibly
    executed tool. Pending (unclaimed) commands survive desktop initialization.
    """

    def __init__(self, directory: Path | None = None):
        self.path = (directory or voice_directory()) / "inbox.sqlite3"
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS commands (
                id TEXT PRIMARY KEY, text TEXT NOT NULL, created REAL NOT NULL,
                expires REAL NOT NULL, state TEXT NOT NULL, detail TEXT NOT NULL
            )""")

    def connect(self):
        # Context management commits and explicitly closes (sqlite's own
        # connection context manager only commits, it does not close).
        return _connection(self.path)

    def enqueue(self, text: str, *, command_id=None, ttl=300.0) -> str:
        text = text.strip()
        if not text or len(text) > 32000:
            raise ValueError("Wake command must contain 1–32000 characters")
        command_id = command_id or uuid.uuid4().hex
        now = time.time()
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO commands VALUES (?, ?, ?, ?, ?, '')",
                       (command_id, text, now, now + ttl, "pending"))
        return command_id

    def claim(self) -> tuple[str, str] | None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE commands SET state='expired' "
                       "WHERE state='pending' AND expires <= ?", (time.time(),))
            row = db.execute("SELECT id, text FROM commands WHERE state='pending' "
                             "ORDER BY created, rowid LIMIT 1").fetchone()
            if row:
                db.execute("UPDATE commands SET state='dispatched' WHERE id=?",
                           (row[0],))
            return row

    def finish(self, command_id: str, state: str, detail=""):
        if state not in ("completed", "failed"):
            raise ValueError(state)
        with self.connect() as db:
            db.execute("UPDATE commands SET state=?, detail=? "
                       "WHERE id=? AND state='dispatched'",
                       (state, detail[:2000], command_id))

    def status(self, command_id: str) -> str | None:
        with self.connect() as db:
            row = db.execute("SELECT state FROM commands WHERE id=?",
                             (command_id,)).fetchone()
            return row[0] if row else None

    def has_pending(self) -> bool:
        with self.connect() as db:
            return db.execute("SELECT 1 FROM commands WHERE state='pending' "
                              "AND expires > ? LIMIT 1", (time.time(),)).fetchone() is not None


@contextmanager
def _connection(path):
    db = sqlite3.connect(path, timeout=0.25)
    try:
        with db:
            yield db
    finally:
        db.close()
