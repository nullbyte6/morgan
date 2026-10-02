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
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from src.init.identity import get_assistant_name
from pathlib import Path

def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


MIGRATIONS = (
    (
        """CREATE TABLE sessions (
            id TEXT PRIMARY KEY, started_at TEXT NOT NULL, ended_at TEXT,
            kind TEXT NOT NULL CHECK(kind IN ('live','imported')),
            metadata TEXT NOT NULL DEFAULT '{}')""",
        """CREATE TABLE messages (
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            sequence INTEGER NOT NULL CHECK(sequence > 0),
            role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
            content TEXT NOT NULL CHECK(length(content) > 0), created_at TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('completed','interrupted','error')),
            source_ref TEXT UNIQUE, UNIQUE(session_id, sequence))""",
        "CREATE INDEX messages_date ON messages(created_at)",
        """CREATE TABLE memories (
            id TEXT PRIMARY KEY, content TEXT NOT NULL CHECK(length(content) BETWEEN 1 AND 4000),
            normalized TEXT NOT NULL, category TEXT NOT NULL
                CHECK(category IN ('preference','fact','project','goal','other')),
            memory_key TEXT, created_at TEXT NOT NULL, modified_at TEXT NOT NULL,
            expires_at TEXT, status TEXT NOT NULL
                CHECK(status IN ('active','superseded','candidate','expired')),
            origin TEXT NOT NULL CHECK(origin IN ('explicit','extracted')),
            confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
            superseded_by TEXT REFERENCES memories(id) ON DELETE SET NULL,
            CHECK(expires_at IS NULL OR expires_at > created_at))""",
        "CREATE UNIQUE INDEX memory_active_text ON memories(normalized) WHERE status='active'",
        "CREATE UNIQUE INDEX memory_active_key ON memories(memory_key) WHERE status='active' AND memory_key IS NOT NULL",
        "CREATE INDEX memory_status ON memories(status, category, modified_at)",
        """CREATE TABLE memory_sources (
            memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
            message_id TEXT REFERENCES messages(id) ON DELETE SET NULL,
            source_ref TEXT NOT NULL, PRIMARY KEY(memory_id, source_ref))""",
        "CREATE INDEX memory_source_message ON memory_sources(message_id)",
        """CREATE TABLE imports (
            path TEXT PRIMARY KEY, size INTEGER NOT NULL, digest TEXT NOT NULL,
            imported_at TEXT NOT NULL, parser_version INTEGER NOT NULL)""",
        "CREATE TABLE deleted_sources (source_ref TEXT PRIMARY KEY, deleted_at TEXT NOT NULL)",
    ),
    (
        "CREATE VIRTUAL TABLE message_fts USING fts5(content, content='messages', content_rowid='rowid', tokenize='unicode61 remove_diacritics 2')",
        """CREATE TRIGGER message_insert AFTER INSERT ON messages BEGIN
            INSERT INTO message_fts(rowid,content) VALUES(new.rowid,new.content); END""",
        """CREATE TRIGGER message_delete AFTER DELETE ON messages BEGIN
            INSERT INTO message_fts(message_fts,rowid,content) VALUES('delete',old.rowid,old.content); END""",
        """CREATE TRIGGER message_update AFTER UPDATE OF content ON messages BEGIN
            INSERT INTO message_fts(message_fts,rowid,content) VALUES('delete',old.rowid,old.content);
            INSERT INTO message_fts(rowid,content) VALUES(new.rowid,new.content); END""",
        "INSERT INTO message_fts(message_fts) VALUES('rebuild')",
        "CREATE VIRTUAL TABLE memory_fts USING fts5(content, content='memories', content_rowid='rowid', tokenize='unicode61 remove_diacritics 2')",
        """CREATE TRIGGER memory_insert AFTER INSERT ON memories BEGIN
            INSERT INTO memory_fts(rowid,content) VALUES(new.rowid,new.content); END""",
        """CREATE TRIGGER memory_delete AFTER DELETE ON memories BEGIN
            INSERT INTO memory_fts(memory_fts,rowid,content) VALUES('delete',old.rowid,old.content); END""",
        """CREATE TRIGGER memory_update AFTER UPDATE OF content ON memories BEGIN
            INSERT INTO memory_fts(memory_fts,rowid,content) VALUES('delete',old.rowid,old.content);
            INSERT INTO memory_fts(rowid,content) VALUES(new.rowid,new.content); END""",
        "INSERT INTO memory_fts(memory_fts) VALUES('rebuild')",
    ),
    ("ALTER TABLE memories ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0 CHECK(pinned IN (0, 1))",),
)


class Database:
    migrations = MIGRATIONS

    def __init__(self, path):
        if str(path).startswith(("\\\\", "//")):
            raise ValueError("Memory database must be on a local disk")
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    @contextmanager
    def connect(self, *, write=False):
        connection = sqlite3.connect(self.path, timeout=0.5)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA secure_delete=ON")
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def migrate(self):
        connection = sqlite3.connect(self.path, timeout=0.5)
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
            versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")]
            if versions != list(range(1, len(versions) + 1)) or len(versions) > len(self.migrations):
                raise RuntimeError(f"Unsupported database schema in {self.path.name}; upgrade {get_assistant_name()} or restore a compatible backup")
            for version, statements in enumerate(self.migrations, 1):
                if version <= len(versions):
                    continue
                for statement in statements:
                    connection.execute(statement)
                connection.execute("INSERT INTO schema_migrations VALUES (?, ?)", (version, timestamp()))
            connection.commit()
        except sqlite3.OperationalError as error:
            connection.rollback()
            if "fts5" in str(error).lower():
                raise RuntimeError(f"{get_assistant_name()} memory requires SQLite with FTS5 enabled") from error
            raise
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def compact(self):
        connection = sqlite3.connect(self.path, timeout=0.5)
        try:
            connection.execute("VACUUM")
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            connection.close()

    def backup(self, destination):
        destination = Path(destination).expanduser().resolve()
        if destination == self.path or destination.exists():
            raise ValueError("Backup destination must be a new file")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb"):
            pass
        source = sqlite3.connect(self.path, timeout=0.5)
        target = sqlite3.connect(destination)
        try:
            source.execute("PRAGMA foreign_keys=ON")
            target.execute("PRAGMA foreign_keys=ON")
            source.backup(target)
        finally:
            target.close()
            source.close()
