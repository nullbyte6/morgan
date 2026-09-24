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

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import AgentEvent, EventType, ExecutionPlan, ExecutionState


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


SCHEMA = (
    """CREATE TABLE IF NOT EXISTS agent_runs (
        id TEXT PRIMARY KEY, task TEXT NOT NULL, state TEXT NOT NULL,
        working_directory TEXT NOT NULL, created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL, completed_at TEXT, final_response TEXT,
        error TEXT, failure_phase TEXT, plan_json TEXT,
        max_steps INTEGER NOT NULL, max_retries INTEGER NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS agent_steps (
        run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
        step_id TEXT NOT NULL, position INTEGER NOT NULL, title TEXT NOT NULL,
        instruction TEXT NOT NULL, tool_name TEXT, tool_args TEXT NOT NULL,
        requires_approval INTEGER NOT NULL, state TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0, output TEXT, error TEXT,
        started_at TEXT, completed_at TEXT,
        PRIMARY KEY (run_id, step_id), UNIQUE (run_id, position)
    )""",
    """CREATE TABLE IF NOT EXISTS agent_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
        event_type TEXT NOT NULL, state TEXT NOT NULL, step_id TEXT,
        payload TEXT NOT NULL, created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS agent_events_run ON agent_events(run_id, id)",
    "CREATE INDEX IF NOT EXISTS agent_runs_state ON agent_runs(state, updated_at)",
)


class AgentStore:
    def __init__(self, path: str | Path):
        if str(path).startswith(("\\\\", "//")):
            raise ValueError("Agent database must be on a local disk")
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect(write=True) as db:
            for statement in SCHEMA:
                db.execute(statement)
            columns = {row[1] for row in db.execute("PRAGMA table_info(agent_runs)")}
            if "failure_phase" not in columns:
                db.execute("ALTER TABLE agent_runs ADD COLUMN failure_phase TEXT")
            if "plan_json" not in columns:
                db.execute("ALTER TABLE agent_runs ADD COLUMN plan_json TEXT")

    @contextmanager
    def connect(self, *, write: bool = False):
        db = sqlite3.connect(self.path, timeout=1.0)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def create_run(self, run_id: str, task: str, state: ExecutionState,
                   working_directory: str, max_steps: int, max_retries: int) -> None:
        now = timestamp()
        with self.connect(write=True) as db:
            db.execute(
                """INSERT INTO agent_runs
                (id,task,state,working_directory,created_at,updated_at,max_steps,max_retries)
                VALUES(?,?,?,?,?,?,?,?)""",
                (run_id, task, state, working_directory, now, now,
                 max_steps, max_retries),
            )

    def set_state(self, run_id: str, state: ExecutionState, *,
                  response: str | None = None, error: str | None = None,
                  failure_phase: str | None = None) -> None:
        completed = timestamp() if state in {
            ExecutionState.COMPLETED, ExecutionState.FAILED,
            ExecutionState.CANCELLED,
        } else None
        with self.connect(write=True) as db:
            db.execute(
                """UPDATE agent_runs SET state=?, updated_at=?,
                completed_at=COALESCE(?,completed_at),
                final_response=COALESCE(?,final_response),
                error=COALESCE(?,error),
                failure_phase=COALESCE(?,failure_phase) WHERE id=?""",
                (state, timestamp(), completed, response, error,
                 failure_phase, run_id),
            )

    def save_plan(self, run_id: str, plan: ExecutionPlan) -> None:
        with self.connect(write=True) as db:
            db.execute(
                "UPDATE agent_runs SET plan_json=?, updated_at=? WHERE id=?",
                (plan.model_dump_json(), timestamp(), run_id),
            )
            for position, step in enumerate(plan.steps, 1):
                db.execute(
                    """INSERT INTO agent_steps
                    (run_id,step_id,position,title,instruction,tool_name,tool_args,
                     requires_approval,state) VALUES(?,?,?,?,?,?,?,?,?)""",
                    (run_id, step.id, position, step.title, step.instruction,
                     step.tool_name, json.dumps(step.tool_args, ensure_ascii=False),
                     int(step.requires_approval), "PENDING"),
                )

    def start_step(self, run_id: str, step_id: str, attempts: int) -> None:
        with self.connect(write=True) as db:
            db.execute(
                """UPDATE agent_steps SET state='RUNNING', attempts=?,
                started_at=COALESCE(started_at,?) WHERE run_id=? AND step_id=?""",
                (attempts, timestamp(), run_id, step_id),
            )

    def finish_step(self, run_id: str, step_id: str, *, success: bool,
                    output: str = "", error: str | None = None) -> None:
        with self.connect(write=True) as db:
            db.execute(
                """UPDATE agent_steps SET state=?, output=?, error=?, completed_at=?
                WHERE run_id=? AND step_id=?""",
                ("COMPLETED" if success else "FAILED", output, error,
                 timestamp(), run_id, step_id),
            )

    def append_event(self, event: AgentEvent) -> AgentEvent:
        created_at = timestamp()
        with self.connect(write=True) as db:
            cursor = db.execute(
                """INSERT INTO agent_events
                (run_id,event_type,state,step_id,payload,created_at)
                VALUES(?,?,?,?,?,?)""",
                (event.run_id, event.type, event.state, event.step_id,
                 json.dumps(event.payload, ensure_ascii=False, default=str), created_at),
            )
        return event.model_copy(update={"id": cursor.lastrowid,
                                        "created_at": created_at})

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM agent_runs WHERE id=?", (run_id,)).fetchone()
            return dict(row) if row else None

    def get_events(self, run_id: str) -> list[AgentEvent]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM agent_events WHERE run_id=? ORDER BY id", (run_id,)
            ).fetchall()
        return [AgentEvent(
            id=row["id"], run_id=row["run_id"],
            type=EventType(row["event_type"]), state=ExecutionState(row["state"]),
            step_id=row["step_id"], payload=json.loads(row["payload"]),
            created_at=row["created_at"],
        ) for row in rows]

    def interrupted_runs(self) -> list[dict[str, Any]]:
        active = tuple(state.value for state in (
            ExecutionState.PLANNING, ExecutionState.EXECUTING,
            ExecutionState.VERIFYING, ExecutionState.AWAITING_APPROVAL,
        ))
        placeholders = ",".join("?" for _ in active)
        with self.connect() as db:
            rows = db.execute(
                f"SELECT * FROM agent_runs WHERE state IN ({placeholders}) ORDER BY updated_at",
                active,
            ).fetchall()
            return [dict(row) for row in rows]
