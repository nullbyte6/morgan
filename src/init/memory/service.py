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
import hashlib
import json
import re
import unicodedata
import uuid
from datetime import datetime, timezone

from .database import Database, timestamp
from .retrieval import UNTRUSTED, bounded, search_history, search_memories

CATEGORIES = {"preference", "fact", "project", "goal", "other"}
SECRET = re.compile(
    r"(?i)(?:password|passwd|contrase[nñ]a|api[_ -]?key|access[_ -]?token|"
    r"refresh[_ -]?token|client[_ -]?secret|private[_ -]?key|bearer)\s*(?:[:=]|is\b|es\b)"
    r"|\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{16,}|AKIA[A-Z0-9]{16})\b"
    r"|-----BEGIN .*PRIVATE KEY-----|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")


def normalize(content):
    return " ".join(unicodedata.normalize("NFKC", content).casefold().split()).rstrip(".。")


def valid_time(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Timestamps must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")


class MemoryService:
    """Local memory API. Each operation owns a short transaction and connection."""
    def __init__(self, path, *, max_results=8, context_chars=4000, recall_chars=8000):
        if not 1 <= max_results <= 50 or not 512 <= context_chars <= 32000 or not 1024 <= recall_chars <= 64000:
            raise ValueError("Invalid memory retrieval limits")
        self.db = Database(path)
        self.max_results = max_results
        self.context_chars = context_chars
        self.recall_chars = recall_chars

    def start_session(self, *, session_id=None, started_at=None, kind="live", metadata=None):
        session_id = session_id or uuid.uuid4().hex
        with self.db.connect(write=True) as db:
            db.execute("INSERT OR IGNORE INTO sessions(id,started_at,kind,metadata) VALUES(?,?,?,?)",
                       (session_id, valid_time(started_at or timestamp()), kind,
                        json.dumps(metadata or {}, ensure_ascii=False)))
        return session_id

    def end_session(self, session_id):
        with self.db.connect(write=True) as db:
            db.execute("UPDATE sessions SET ended_at=? WHERE id=?", (timestamp(), session_id))

    def get_session(self, session_id):
        with self.db.connect() as db:
            row = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            return dict(row) if row else None

    def health(self):
        with self.db.connect() as db:
            return {"integrity": [row[0] for row in db.execute("PRAGMA integrity_check")],
                    "foreign_key_errors": [list(row) for row in db.execute("PRAGMA foreign_key_check")],
                    "schema_version": db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]}

    def record_message(self, session_id, role, content, *, message_id=None, created_at=None,
                       status="completed", source_ref=None):
        with self.db.connect(write=True) as db:
            return self._record(db, session_id, role, content, message_id=message_id,
                                created_at=created_at, status=status, source_ref=source_ref)

    @staticmethod
    def _record(db, session_id, role, content, *, message_id=None, created_at=None,
                status="completed", source_ref=None):
        if not content.strip():
            raise ValueError("Message must not be empty")
        message_id = message_id or uuid.uuid4().hex
        existing = db.execute("SELECT id,content,role,session_id FROM messages WHERE id=?", (message_id,)).fetchone()
        if existing:
            if (existing["content"], existing["role"], existing["session_id"]) != (content, role, session_id):
                raise ValueError("Message identifier already belongs to different content")
            return message_id
        if source_ref:
            if db.execute("SELECT 1 FROM deleted_sources WHERE source_ref=?", (source_ref,)).fetchone():
                return None
            existing = db.execute("SELECT id FROM messages WHERE source_ref=?", (source_ref,)).fetchone()
            if existing:
                return existing["id"]
        sequence = db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM messages WHERE session_id=?",
                              (session_id,)).fetchone()[0]
        db.execute("""INSERT INTO messages(id,session_id,sequence,role,content,created_at,status,source_ref)
            VALUES(?,?,?,?,?,?,?,?)""", (message_id, session_id, sequence, role, content,
                                         valid_time(created_at or timestamp()), status, source_ref))
        return message_id

    def messages(self, session_id, *, after=0, limit=100):
        with self.db.connect() as db:
            return [dict(row) for row in db.execute("""SELECT * FROM messages
                WHERE session_id=? AND sequence > ? ORDER BY sequence LIMIT ?""",
                                                   (session_id, after, min(max(1, limit), 500)))]

    @staticmethod
    def _validate_memory(content, category, key, expires_at, confidence):
        content = content.strip()
        if not 1 <= len(content) <= 4000 or not normalize(content):
            raise ValueError("Memory content must contain 1–4000 characters")
        if SECRET.search(content):
            raise ValueError("Credentials and secrets cannot be stored as ordinary memories")
        if category not in CATEGORIES:
            raise ValueError("Unsupported memory category")
        if key is not None:
            key = normalize(key)
            if not re.fullmatch(r"[\w.-]{1,100}", key):
                raise ValueError("Memory key must contain 1–100 letters, numbers, dots, hyphens or underscores")
        if not 0 <= confidence <= 1:
            raise ValueError("Confidence must be between zero and one")
        expires_at = valid_time(expires_at) if expires_at else None
        if expires_at is not None and expires_at <= timestamp():
            raise ValueError("Expiration must be in the future")
        return content, key, expires_at

    @staticmethod
    def _expire(db):
        db.execute("UPDATE memories SET status='expired',modified_at=? WHERE status='active' AND expires_at <= ?",
                   (timestamp(), timestamp()))

    @staticmethod
    def _source(db, memory_id, message_id, source_ref):
        if message_id:
            row = db.execute("SELECT source_ref FROM messages WHERE id=?", (message_id,)).fetchone()
            if row is None:
                raise ValueError("Source message does not exist")
            source_ref = row[0] or "message:" + message_id
        db.execute("INSERT OR IGNORE INTO memory_sources VALUES(?,?,?)",
                   (memory_id, message_id, source_ref or "explicit:manual"))

    def remember(self, content, *, category="fact", key=None, expires_at=None,
                 origin="explicit", confidence=1.0, source_message_id=None, source_ref=None,
                 supersedes=None):
        content, key, expires_at = self._validate_memory(content, category, key, expires_at, confidence)
        if origin not in ("explicit", "extracted"):
            raise ValueError("Unsupported memory origin")
        if origin != "explicit" and supersedes:
            raise ValueError("Unconfirmed extraction cannot supersede a confirmed memory")
        status = "active" if origin == "explicit" else "candidate"
        with self.db.connect(write=True) as db:
            self._expire(db)
            existing = db.execute("SELECT * FROM memories WHERE normalized=? AND status=?",
                                  (normalize(content), status)).fetchone()
            previous = db.execute("SELECT * FROM memories WHERE id=?", (supersedes,)).fetchone() if supersedes else None
            if supersedes and (previous is None or previous["status"] != "active"):
                raise ValueError("Only an active memory can be superseded")
            keyed = db.execute("SELECT * FROM memories WHERE memory_key=? AND status='active'", (key,)).fetchone() if key and status == "active" else None
            previous_ids = {row["id"] for row in (previous, keyed) if row is not None}
            if existing:
                memory_id = existing["id"]
                previous_ids.discard(memory_id)
            else:
                memory_id = uuid.uuid4().hex
            for previous_id in previous_ids:
                db.execute("UPDATE memories SET status='superseded',modified_at=? WHERE id=?", (timestamp(), previous_id))
            if not existing:
                now = timestamp()
                db.execute("""INSERT INTO memories(id,content,normalized,category,memory_key,created_at,
                    modified_at,expires_at,status,origin,confidence) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                           (memory_id, content, normalize(content), category, key, now, now,
                            expires_at, status, origin, confidence))
            elif key and existing["memory_key"] != key:
                db.execute("UPDATE memories SET memory_key=?,category=?,modified_at=? WHERE id=?",
                           (key, category, timestamp(), memory_id))
            for previous_id in previous_ids:
                db.execute("UPDATE memories SET superseded_by=? WHERE id=?", (memory_id, previous_id))
            self._source(db, memory_id, source_message_id, source_ref)
        return self.get_memory(memory_id)

    def get_memory(self, memory_id):
        with self.db.connect() as db:
            row = db.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
            if row is None:
                return None
            result = dict(row)
            if result["status"] == "active" and result["expires_at"] and result["expires_at"] <= timestamp():
                result["status"] = "expired"
            result.pop("normalized")
            result["sources"] = [dict(source) for source in db.execute(
                "SELECT message_id,source_ref FROM memory_sources WHERE memory_id=? ORDER BY source_ref LIMIT 20", (memory_id,))]
            return result

    def update_memory(self, memory_id, content, *, category="fact", key=None, expires_at=None,
                      source_message_id=None):
        content, key, expires_at = self._validate_memory(content, category, key, expires_at, 1.0)
        with self.db.connect(write=True) as db:
            self._expire(db)
            current = db.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
            if current is None or current["status"] not in ("active", "candidate"):
                raise ValueError("Memory is missing or no longer current")
            db.execute("""UPDATE memories SET content=?,normalized=?,category=?,memory_key=?,expires_at=?,
                modified_at=?,status='active',origin='explicit',confidence=1 WHERE id=?""",
                       (content, normalize(content), category, key or current["memory_key"], expires_at, timestamp(), memory_id))
            self._source(db, memory_id, source_message_id, None)
        return self.get_memory(memory_id)

    def delete_memory(self, memory_id):
        with self.db.connect(write=True) as db:
            return db.execute("DELETE FROM memories WHERE id=?", (memory_id,)).rowcount == 1

    def list_memories(self, *, category=None, include_inactive=False, limit=None, offset=0):
        limit = min(self.max_results, max(1, limit or self.max_results))
        with self.db.connect() as db:
            rows = [dict(row) for row in db.execute("""SELECT id,content,category,memory_key,status,
                created_at,modified_at,expires_at,origin,confidence FROM memories
                WHERE (? OR (status='active' AND (expires_at IS NULL OR expires_at > ?)))
                  AND (? IS NULL OR category=?) ORDER BY modified_at DESC,id LIMIT ? OFFSET ?""",
                (include_inactive, timestamp(), category, category, limit, max(0, offset)))]
        return bounded(rows, self.recall_chars)

    def recall(self, query, *, history=True, limit=None):
        limit = min(self.max_results, max(1, limit or self.max_results))
        with self.db.connect() as db:
            memories = search_memories(db, query, limit)
            conversations = search_history(db, query, limit) if history else []
        budget = self.recall_chars - len(UNTRUSTED) - 100
        selected = bounded(memories, budget // 2 if conversations else budget)
        remaining = budget - len(json.dumps(selected, ensure_ascii=False))
        return {"warning": UNTRUSTED, "memories": selected,
                "conversations": bounded(conversations, remaining)}

    def context(self):
        with self.db.connect() as db:
            rows = [dict(row) for row in db.execute("""SELECT id,content,category FROM memories
                WHERE status='active' AND origin='explicit' AND category='preference'
                AND (expires_at IS NULL OR expires_at > ?) ORDER BY modified_at DESC,id LIMIT ?""",
                                                   (timestamp(), self.max_results))]
        selected = bounded(rows, self.context_chars - len(UNTRUSTED) - 2)
        return UNTRUSTED + "\n" + json.dumps(selected, ensure_ascii=False) if selected else ""

    def delete_message(self, message_id):
        with self.db.connect(write=True) as db:
            row = db.execute("SELECT source_ref FROM messages WHERE id=?", (message_id,)).fetchone()
            if row is None:
                return False
            if row[0]:
                db.execute("INSERT OR IGNORE INTO deleted_sources VALUES(?,?)", (row[0], timestamp()))
            db.execute("DELETE FROM messages WHERE id=?", (message_id,))
            return True

    def backup(self, destination):
        self.db.backup(destination)

    def import_markdown(self, path, *, role_map, include_tail=False):
        from .markdown import read_log
        parsed = read_log(path, role_map=role_map, include_tail=include_tail)
        if parsed["error"]:
            return parsed
        data = parsed.pop("data")
        entries = parsed.pop("entries")
        digest = hashlib.sha256(data).hexdigest()
        path = parsed["path"]
        imported = 0
        with self.db.connect(write=True) as db:
            previous = db.execute("SELECT * FROM imports WHERE path=?", (path,)).fetchone()
            if previous and (len(data) < previous["size"] or hashlib.sha256(data[:previous["size"]]).hexdigest() != previous["digest"]):
                return {"path": path, "imported": 0, "error": "Source was rewritten or truncated; explicit review required"}
            session_id = "log-" + hashlib.sha256(path.encode()).hexdigest()
            for entry in entries:
                source_ref = path + "#byte=" + str(entry["offset"])
                existing = db.execute("""SELECT m.content,s.kind FROM messages m
                    JOIN sessions s ON s.id=m.session_id WHERE m.source_ref=?""", (source_ref,)).fetchone()
                if existing and existing["kind"] == "imported" and existing["content"] != entry["content"]:
                    return {"path": path, "imported": 0, "error": "Previously imported entry changed; explicit review required"}
            if entries:
                db.execute("INSERT OR IGNORE INTO sessions(id,started_at,kind,metadata) VALUES(?,?,?,?)",
                           (session_id, entries[0]["created_at"], "imported", json.dumps({"path": path, "session_boundaries": "unknown"})))
            for entry in entries:
                source_ref = path + "#byte=" + str(entry["offset"])
                exists = db.execute("SELECT 1 FROM messages WHERE source_ref=?", (source_ref,)).fetchone()
                result = self._record(db, session_id, entry["role"], entry["content"],
                                      message_id=uuid.uuid5(uuid.NAMESPACE_URL, source_ref).hex,
                                      created_at=entry["created_at"], source_ref=source_ref)
                if result and not exists:
                    imported += 1
            if parsed["sealed_size"]:
                size = parsed["sealed_size"]
                db.execute("""INSERT INTO imports VALUES(?,?,?,?,1) ON CONFLICT(path) DO UPDATE SET
                    size=excluded.size,digest=excluded.digest,imported_at=excluded.imported_at""",
                           (path, size, hashlib.sha256(data[:size]).hexdigest(), timestamp()))
        return {**parsed, "imported": imported, "digest": digest}
