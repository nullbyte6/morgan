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

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ExecutionState(StrEnum):
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class EventType(StrEnum):
    RUN_CREATED = "run_created"
    STATE_CHANGED = "state_changed"
    PLAN_CREATED = "plan_created"
    PROJECT_INSPECTED = "project_inspected"
    PLAN_VALIDATED = "plan_validated"
    STEP_STARTED = "step_started"
    TOOL_CALLED = "tool_called"
    TOOL_RESULT = "tool_result"
    STEP_COMPLETED = "step_completed"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_RESOLVED = "approval_resolved"
    VERIFICATION_COMPLETED = "verification_completed"
    ERROR = "error"
    PLANNING_FAILED = "planning_failed"
    EXECUTION_FAILED = "execution_failed"
    VERIFICATION_FAILED = "verification_failed"
    FINAL_RESULT = "final_result"


class PlanStep(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1, max_length=200)
    instruction: str = Field(min_length=1, max_length=4000)
    tool_name: str = Field(min_length=1, max_length=100)
    tool_args: dict[str, Any] = Field(default_factory=dict)
    requires_approval: bool = False


class PlanDraftStep(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1, max_length=96)
    instruction: str = Field(min_length=1, max_length=320)
    tool_name: str = Field(min_length=1, max_length=100)
    requires_approval: bool = False


class ExecutionPlanDraft(BaseModel):
    goal: str = Field(min_length=1, max_length=320)
    steps: list[PlanDraftStep] = Field(min_length=1, max_length=6)


class InspectedFile(BaseModel):
    path: str
    content: str
    bytes_read: int
    sha256: str
    truncated: bool = False


class ProjectContext(BaseModel):
    working_directory: str
    repository_root: str | None = None
    discovered_files: list[str] = Field(default_factory=list)
    files: list[InspectedFile] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ProjectFileSelection(BaseModel):
    paths: list[str] = Field(default_factory=list, max_length=8)


class ExecutionPlan(BaseModel):
    request_id: str = Field(min_length=32, max_length=32,
                            pattern=r"^[a-f0-9]{32}$")
    goal: str = Field(min_length=1, max_length=4000)
    steps: list[PlanStep] = Field(min_length=1)
    project_context: ProjectContext | None = None


class StepResult(BaseModel):
    success: bool
    output: str = ""
    error: str | None = None


class VerificationResult(BaseModel):
    success: bool
    summary: str = ""


class AgentEvent(BaseModel):
    id: int | None = None
    run_id: str
    type: EventType
    state: ExecutionState
    step_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None


class RunResult(BaseModel):
    run_id: str
    state: ExecutionState
    response: str = ""
    error: str | None = None
    failure_phase: str | None = None
    plan: ExecutionPlan | None = None
    steps: list[StepResult] = Field(default_factory=list)
