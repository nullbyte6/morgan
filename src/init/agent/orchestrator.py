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

import asyncio
import inspect
import os
import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

from .models import (
    AgentEvent,
    EventType,
    ExecutionPlan,
    ExecutionState,
    RunResult,
    StepResult,
    VerificationResult,
)
from .persistence import AgentStore


class AgentBackend(Protocol):
    async def plan(self, task: str, max_steps: int) -> ExecutionPlan: ...
    async def execute(self, instruction: str, observations: list[str]) -> str: ...
    async def verify(self, task: str, plan: ExecutionPlan,
                     observations: list[str]) -> VerificationResult: ...
    async def finalize(self, task: str, observations: list[str],
                       verification: VerificationResult) -> str: ...


TRANSITIONS = {
    ExecutionState.PLANNING: {
        ExecutionState.EXECUTING, ExecutionState.FAILED, ExecutionState.CANCELLED,
    },
    ExecutionState.EXECUTING: {
        ExecutionState.VERIFYING, ExecutionState.AWAITING_APPROVAL,
        ExecutionState.PAUSED, ExecutionState.FAILED, ExecutionState.CANCELLED,
    },
    ExecutionState.AWAITING_APPROVAL: {
        ExecutionState.EXECUTING, ExecutionState.PAUSED,
        ExecutionState.FAILED, ExecutionState.CANCELLED,
    },
    ExecutionState.PAUSED: {
        ExecutionState.EXECUTING, ExecutionState.CANCELLED,
    },
    ExecutionState.VERIFYING: {
        ExecutionState.COMPLETED, ExecutionState.FAILED, ExecutionState.CANCELLED,
    },
    ExecutionState.COMPLETED: set(),
    ExecutionState.FAILED: set(),
    ExecutionState.CANCELLED: set(),
}


class AgentOrchestrator:
    def __init__(self, backend: AgentBackend, tools: Mapping[str, Callable[..., Any]],
                 store: AgentStore, *, max_steps: int = 12, max_retries: int = 2,
                 destructive_tools: set[str] | None = None):
        if max_steps < 1 or max_retries < 0:
            raise ValueError("Agent limits must be positive")
        self.backend = backend
        self.tools = dict(tools)
        self.store = store
        self.max_steps = max_steps
        self.max_retries = max_retries
        self.destructive_tools = destructive_tools or {
            "delete_directory", "delete_file", "empty_recycle_bin",
            "shutdown_computer", "kill_process", "uninstall_app",
            "clean_app_residue", "git_push", "update_repo", "execute_command",
            "send_email", "send_email_draft", "send_message", "edit_file",
            "append_file", "replace_in_file", "write_binary_file", "git_add",
            "git_commit", "git_pull", "git_switch", "install_app",
            "close_application", "schedule_notification", "start_timer",
        }
        self._states: dict[str, ExecutionState] = {}

    async def run(self, task: str, *, cancel_event=None,
                  pause_event=None,
                  approval: Callable[[str], bool | Awaitable[bool]] | None = None,
                  on_event: Callable[[AgentEvent], Any] | None = None,
                  working_directory: str | None = None) -> RunResult:
        run_id = uuid.uuid4().hex
        state = ExecutionState.PLANNING
        self._states[run_id] = state
        self.store.create_run(
            run_id, task, state, working_directory or os.getcwd(),
            self.max_steps, self.max_retries,
        )
        self._emit(run_id, EventType.RUN_CREATED, on_event,
                   {"task": task, "max_steps": self.max_steps,
                    "max_retries": self.max_retries})
        plan = None
        results: list[StepResult] = []
        observations: list[str] = []
        try:
            self._check_cancelled(cancel_event)
            plan = await self._await_cancellable(
                self.backend.plan(task, self.max_steps), cancel_event)
            if len(plan.steps) > self.max_steps:
                raise ValueError(
                    f"Plan contains {len(plan.steps)} steps; limit is {self.max_steps}")
            self.store.save_plan(run_id, plan)
            self._emit(run_id, EventType.PLAN_CREATED, on_event,
                       plan.model_dump(mode="json"))
            self._transition(run_id, ExecutionState.EXECUTING, on_event)

            for step in plan.steps:
                self._check_cancelled(cancel_event)
                await self._wait_if_paused(run_id, pause_event, cancel_event, on_event)
                needs_approval = bool(
                    step.requires_approval or step.tool_name in self.destructive_tools)
                if needs_approval:
                    self._transition(run_id, ExecutionState.AWAITING_APPROVAL, on_event)
                    message = f"{step.title}: {step.instruction}"
                    self._emit(run_id, EventType.APPROVAL_REQUESTED, on_event,
                               {"message": message, "tool_name": step.tool_name}, step.id)
                    if approval is None:
                        self._transition(run_id, ExecutionState.PAUSED, on_event)
                        return RunResult(run_id=run_id, state=ExecutionState.PAUSED,
                                         plan=plan, steps=results)
                    accepted = approval(message)
                    if inspect.isawaitable(accepted):
                        accepted = await accepted
                    self._emit(run_id, EventType.APPROVAL_RESOLVED, on_event,
                               {"accepted": bool(accepted)}, step.id)
                    if not accepted:
                        raise PermissionError(f"Approval denied for step {step.id}")
                    self._transition(run_id, ExecutionState.EXECUTING, on_event)

                result = await self._run_step(
                    run_id, step, observations, cancel_event, on_event)
                results.append(result)
                if not result.success:
                    raise RuntimeError(result.error or f"Step {step.id} failed")
                observations.append(f"{step.title}: {result.output}")

            self._transition(run_id, ExecutionState.VERIFYING, on_event)
            self._check_cancelled(cancel_event)
            verification = await self._await_cancellable(
                self.backend.verify(task, plan, observations), cancel_event)
            self._emit(run_id, EventType.VERIFICATION_COMPLETED, on_event,
                       verification.model_dump(mode="json"))
            if not verification.success:
                raise RuntimeError(verification.summary or "Verification failed")
            response = await self._await_cancellable(
                self.backend.finalize(task, observations, verification), cancel_event)
            self._transition(run_id, ExecutionState.COMPLETED, on_event,
                             response=response)
            self._emit(run_id, EventType.FINAL_RESULT, on_event,
                       {"response": response})
            return RunResult(run_id=run_id, state=ExecutionState.COMPLETED,
                             response=response, plan=plan, steps=results)
        except asyncio.CancelledError:
            return self._cancel(run_id, plan, results, on_event)
        except Exception as error:
            if self._cancelled(cancel_event):
                return self._cancel(run_id, plan, results, on_event)
            message = str(error)
            self._emit(run_id, EventType.ERROR, on_event,
                       {"error": message, "type": type(error).__name__})
            self._transition(run_id, ExecutionState.FAILED, on_event, error=message)
            return RunResult(run_id=run_id, state=ExecutionState.FAILED,
                             error=message, plan=plan, steps=results)
        finally:
            self._states.pop(run_id, None)

    async def _run_step(self, run_id, step, observations, cancel_event,
                        on_event) -> StepResult:
        last_error = None
        for attempt in range(1, self.max_retries + 2):
            self._check_cancelled(cancel_event)
            self.store.start_step(run_id, step.id, attempt)
            self._emit(run_id, EventType.STEP_STARTED, on_event,
                       {"attempt": attempt, "title": step.title}, step.id)
            try:
                if step.tool_name:
                    tool = self.tools.get(step.tool_name)
                    if tool is None:
                        raise LookupError(f"Unknown tool: {step.tool_name}")
                    self._emit(run_id, EventType.TOOL_CALLED, on_event,
                               {"tool_name": step.tool_name,
                                "arguments": step.tool_args}, step.id)
                    output = tool(**step.tool_args)
                    if inspect.isawaitable(output):
                        output = await self._await_cancellable(output, cancel_event)
                    output = str(output)
                    self._emit(run_id, EventType.TOOL_RESULT, on_event,
                               {"tool_name": step.tool_name, "output": output}, step.id)
                else:
                    output = await self._await_cancellable(
                        self.backend.execute(step.instruction, observations),
                        cancel_event)
                result = StepResult(success=True, output=output)
                self.store.finish_step(run_id, step.id, success=True, output=output)
                self._emit(run_id, EventType.STEP_COMPLETED, on_event,
                           result.model_dump(mode="json"), step.id)
                return result
            except asyncio.CancelledError:
                self.store.finish_step(
                    run_id, step.id, success=False,
                    error="Execution cancelled")
                result = StepResult(success=False, error="Execution cancelled")
                self._emit(run_id, EventType.STEP_COMPLETED, on_event,
                           result.model_dump(mode="json"), step.id)
                raise
            except Exception as error:
                last_error = str(error)
                if attempt > self.max_retries:
                    self.store.finish_step(
                        run_id, step.id, success=False, error=last_error)
                    result = StepResult(success=False, error=last_error)
                    self._emit(run_id, EventType.STEP_COMPLETED, on_event,
                               result.model_dump(mode="json"), step.id)
                    return result
                self._emit(run_id, EventType.ERROR, on_event,
                           {"error": last_error, "attempt": attempt,
                            "retrying": True}, step.id)
        return StepResult(success=False, error=last_error)

    def _transition(self, run_id: str, state: ExecutionState, on_event,
                    *, response: str | None = None,
                    error: str | None = None) -> None:
        current = self._states[run_id]
        if state not in TRANSITIONS[current]:
            raise RuntimeError(f"Invalid agent transition: {current} -> {state}")
        self._states[run_id] = state
        self.store.set_state(run_id, state, response=response, error=error)
        self._emit(run_id, EventType.STATE_CHANGED, on_event,
                   {"from": current, "to": state})

    def _emit(self, run_id: str, event_type: EventType, callback,
              payload: dict[str, Any], step_id: str | None = None) -> None:
        event = self.store.append_event(AgentEvent(
            run_id=run_id, type=event_type, state=self._states[run_id],
            step_id=step_id, payload=payload,
        ))
        if callback is not None:
            callback(event)

    def _cancel(self, run_id, plan, results, on_event) -> RunResult:
        self._transition(run_id, ExecutionState.CANCELLED, on_event,
                         error="Execution cancelled")
        return RunResult(run_id=run_id, state=ExecutionState.CANCELLED,
                         error="Execution cancelled", plan=plan, steps=results)

    @staticmethod
    def _cancelled(cancel_event) -> bool:
        return cancel_event is not None and cancel_event.is_set()

    def _check_cancelled(self, cancel_event) -> None:
        if self._cancelled(cancel_event):
            raise asyncio.CancelledError

    async def _await_cancellable(self, awaitable, cancel_event):
        task = asyncio.ensure_future(awaitable)
        while not task.done():
            if self._cancelled(cancel_event):
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                raise asyncio.CancelledError
            await asyncio.wait({task}, timeout=0.05)
        return await task

    async def _wait_if_paused(self, run_id, pause_event, cancel_event,
                              on_event) -> None:
        if pause_event is None or not pause_event.is_set():
            return
        self._transition(run_id, ExecutionState.PAUSED, on_event)
        while pause_event.is_set():
            self._check_cancelled(cancel_event)
            await asyncio.sleep(0.05)
        self._transition(run_id, ExecutionState.EXECUTING, on_event)
