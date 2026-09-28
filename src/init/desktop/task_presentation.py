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
"""A shared desktop projection of TaskControl and observable transport events."""

import json
from dataclasses import dataclass, replace

from PySide6.QtCore import QObject, Signal, Slot

from src.init.task_activity import TaskActivity
from src.init.task_state import normalize_task_title


@dataclass(frozen=True)
class TaskView:
    turn_id: int = 0
    task_id: str = ""
    lifecycle: str = "idle"
    active: bool = False
    permission: bool = False
    denied: bool = False
    settled: bool = False
    speaking: bool = False
    writing: bool = False
    executing: bool = False
    category: str = ""
    subject: str = ""
    title: str = ""
    started: int = 0
    completed: int = 0
    step_detail: tuple | None = None

    @property
    def state(self):
        if self.permission or self.lifecycle == "waiting":
            return "waiting"
        if self.denied or self.lifecycle in {"blocked", "failed"}:
            return "error"
        if self.lifecycle in {"interrupted", "cancelled", "limit_reached"}:
            return "stopped"
        return "finished" if self.lifecycle == "complete" else "running"

    @property
    def orb_state(self):
        if self.settled:
            return "idle"
        if self.state == "waiting":
            return "awaiting_permission"
        if self.state == "error":
            return "denied_error"
        if self.state == "stopped" or self.lifecycle == "idle":
            return "idle"
        if self.lifecycle == "complete":
            return "success"
        if self.speaking:
            return "reading"
        if self.executing:
            return "executing"
        return "writing" if self.writing else "processing"

    @property
    def activity(self):
        if self.permission:
            return "permission", ""
        if self.lifecycle == "waiting":
            return self.category or "waiting", ""
        if self.active and self.lifecycle == "active" and not self.denied:
            return self.category, self.subject
        return "", ""


class TaskPresentation(QObject):
    changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = TaskView()

    def _update(self, **values):
        view = replace(self.view, **values)
        if view != self.view:
            self.view = view
            self.changed.emit(view)

    def begin(self, turn_id):
        self.view = TaskView(turn_id=turn_id, lifecycle="active", active=True)
        self.changed.emit(self.view)

    @Slot(int, object)
    def on_activity(self, turn_id, activity):
        if (turn_id != self.view.turn_id or not self.view.active
                or not isinstance(activity, TaskActivity)
                or (self.view.task_id and activity.task_id != self.view.task_id
                    and activity.event != "resumed")):
            return
        started = self.view.started + (activity.event == "started")
        completed = self.view.completed + (activity.event == "finished")
        self._update(task_id=activity.task_id, lifecycle=activity.lifecycle,
                     executing=activity.event == "started", writing=False,
                     category=activity.category, subject=activity.subject,
                     started=started, completed=completed)

    @Slot(int, str)
    def on_phase(self, turn_id, phase):
        if turn_id != self.view.turn_id or not self.view.active or not phase.startswith("step:"):
            return
        try:
            detail = json.loads(phase[5:])
        except ValueError:
            return
        if (not isinstance(detail, dict)
                or detail.get("kind") not in {"inspect", "execute", "verify", "checkpoint", "failed", "skipped"}
                or not isinstance(detail.get("tool"), str)
                or not isinstance(detail.get("subject", ""), str)):
            return
        self._update(step_detail=(detail["kind"], " ".join(detail["tool"].split())[:80],
                                  " ".join(detail.get("subject", "").split())[:80], self.view.completed))

    @Slot(int, str)
    def set_task_title(self, turn_id, title):
        if turn_id == self.view.turn_id and self.view.active and not self.view.title:
            self._update(title=normalize_task_title(title))

    def awaiting_permission(self, turn_id, *, waiting=True):
        if turn_id == self.view.turn_id and self.view.active:
            self._update(permission=waiting)

    def permission_denied(self, turn_id):
        if turn_id == self.view.turn_id and self.view.active:
            self._update(denied=True, permission=False)

    def speaking(self, turn_id, speaking):
        if turn_id == self.view.turn_id:
            self._update(speaking=speaking)

    def writing(self, turn_id):
        if turn_id == self.view.turn_id and self.view.active:
            self._update(writing=True)

    def finish(self, turn_id, *, interrupted=False, failed=False):
        if turn_id != self.view.turn_id or not self.view.active:
            return
        lifecycle = ("interrupted" if interrupted else "failed" if failed
                     else self.view.lifecycle if self.view.task_id else "complete")
        if lifecycle == "active":
            lifecycle = "interrupted"
        self._update(active=False, lifecycle=lifecycle, permission=False, speaking=False,
                     writing=False, executing=False,
                     category=self.view.category if lifecycle == "waiting" else "", subject="")

    def settle(self, turn_id):
        if turn_id == self.view.turn_id and not self.view.active and self.view.lifecycle in {"complete", "failed"}:
            self._update(settled=True)
