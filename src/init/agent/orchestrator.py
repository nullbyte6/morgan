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
import hashlib
from pathlib import Path
import inspect
import json
import logging
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
    async def validate_plan(self, task: str,
                            plan: ExecutionPlan) -> VerificationResult: ...
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
        mandatory_approval_tools = {
            "create_file", "edit_file", "append_file", "replace_in_file",
            "write_binary_file", "delete_file", "delete_directory",
        }

        self.destructive_tools = mandatory_approval_tools | (destructive_tools if destructive_tools is not None else {
            "delete_directory", "delete_file", "empty_recycle_bin",
            "shutdown_computer", "kill_process", "uninstall_app",
            "clean_app_residue", "git_push", "update_repo", "execute_command",
            "send_email", "send_email_draft", "send_message", "edit_file",
            "create_file", "append_file", "replace_in_file",
            "write_binary_file", "git_add", "git_commit", "git_pull",
            "git_switch", "install_app", "close_application",
            "schedule_notification", "start_timer",
            "delete_email", "forget", "update_config", "git_fetch",
            "kill_self", "cancel_timer", "send_notification",
        })
        self._states: dict[str, ExecutionState] = {}

    @staticmethod
    def _append_target(step, working_directory: str):
        """Fail closed: validate an append-only operation before approval/execution."""
        if step.tool_name != "append_file":
            return None
        args = step.tool_args
        path = args.get("path")
        content = args.get("content", args.get("text"))
        if not isinstance(path, str) or not path.strip():
            raise ValueError("append_file requires a concrete path")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("append_file requires non-empty content")
        target = Path(path).expanduser()
        if not target.is_absolute():
            target = Path(working_directory) / target
        target = target.resolve(strict=True)
        if not target.is_file() or target.is_symlink():
            raise ValueError("append_file target must be an existing regular file")
        return target

    @classmethod
    def _append_snapshot(cls, step, working_directory: str):
        target = cls._append_target(step, working_directory)
        if target is None:
            return None
        return hashlib.sha256(target.read_bytes()).hexdigest()

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
            plan_validation = await self._await_cancellable(
                self.backend.validate_plan(task, plan), cancel_event)
            self._emit(run_id, EventType.PLAN_VALIDATED, on_event,
                       plan_validation.model_dump(mode="json"))
            if not plan_validation.success:
                raise RuntimeError(
                    "Plan validation failed: "
                    + (plan_validation.summary or "plan does not match the request"))
            self._transition(run_id, ExecutionState.EXECUTING, on_event)

            for step in plan.steps:
                self._check_cancelled(cancel_event)
                await self._wait_if_paused(run_id, pause_event, cancel_event, on_event)
                needs_approval = bool(
                    step.requires_approval or step.tool_name in self.destructive_tools)
                if needs_approval:
                    self._transition(run_id, ExecutionState.AWAITING_APPROVAL, on_event)
                    message = f"{step.title}: {step.instruction}"
                    snapshot = self._append_snapshot(step, working_directory or os.getcwd())
                    if snapshot is not None:
                        message += f"\nAPPEND_SHA256:{snapshot}\nAPPEND_CONTENT:{step.tool_args.get('content', step.tool_args.get('text'))}"
                    self.store.register_approval(
                        run_id, step.id, step.tool_name, step.tool_args, message)
                    self._emit(run_id, EventType.APPROVAL_REQUESTED, on_event,
                               {"message": message, "tool_name": step.tool_name,
                                "arguments": step.tool_args}, step.id)
                    if approval is None:
                        return RunResult(run_id=run_id,
                                         state=ExecutionState.AWAITING_APPROVAL,
                                         plan=plan, steps=results)
                    accepted = approval(message)
                    if inspect.isawaitable(accepted):
                        accepted = await accepted
                    if not self.store.resolve_approval(
                            run_id, step.id, bool(accepted)):
                        raise RuntimeError("Approval is no longer pending")
                    self._emit(run_id, EventType.APPROVAL_RESOLVED, on_event,
                               {"accepted": bool(accepted)}, step.id)
                    if not accepted:
                        raise PermissionError(f"Approval denied for step {step.id}")
                    if snapshot is not None and self._append_snapshot(
                            step, working_directory or os.getcwd()) != snapshot:
                        raise RuntimeError("Append target changed during approval")
                    self._transition(run_id, ExecutionState.EXECUTING, on_event)

                result = await self._run_step(
                    run_id, step, observations, cancel_event, on_event)
                results.append(result)
                if not result.success:
                    raise RuntimeError(result.error or f"Step {step.id} failed")
                observations.append(
                    f"Tool {step.tool_name} completed step {step.id} "
                    f"({step.title}) successfully. Result: {result.output}")

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
            logging.getLogger("arlo.agent").exception(
                "Agent run %s failed in state %s", run_id,
                self._states[run_id].value)
            message = f"{type(error).__name__}: {error}"
            failed_state = self._states[run_id]
            phase, event_type = self._failure_details(failed_state)
            payload = {"error": message, "type": type(error).__name__,
                       "phase": phase}
            self._emit(run_id, event_type, on_event, payload)
            self._emit(run_id, EventType.ERROR, on_event, payload)
            self._transition(run_id, ExecutionState.FAILED, on_event,
                             error=message, failure_phase=phase)
            return RunResult(run_id=run_id, state=ExecutionState.FAILED,
                             error=message, failure_phase=phase,
                             plan=plan, steps=results)
        finally:
            self._states.pop(run_id, None)

    async def resume_approval(self, run_id: str, step_id: str, accepted: bool,
                              *, cancel_event=None, on_event=None) -> RunResult:
        pending = next((item for item in self.store.pending_approvals()
                        if item["run_id"] == run_id
                        and item["step_id"] == step_id), None)
        if pending is None or not pending.get("plan_json"):
            raise LookupError("Approval is stale or is not registered")
        plan = ExecutionPlan.model_validate_json(pending["plan_json"])
        step_index = next((index for index, step in enumerate(plan.steps)
                           if step.id == step_id), None)
        if step_index is None:
            raise LookupError("Approved step is not part of the stored plan")
        step = plan.steps[step_index]
        if (step.tool_name != pending["tool_name"]
                or step.tool_args != pending["tool_args"]):
            raise RuntimeError("Stored approval does not match the planned operation")
        if step.tool_name == "append_file":
            expected = pending["proposed_change"].split("APPEND_SHA256:")[-1].splitlines()[0] if "APPEND_SHA256:" in pending["proposed_change"] else None
            if not expected or self._append_snapshot(step, pending["working_directory"]) != expected:
                raise RuntimeError("Append target changed since approval was requested")
        self._states[run_id] = ExecutionState.AWAITING_APPROVAL
        results = []
        observations = []
        for stored, planned in zip(self.store.get_steps(run_id), plan.steps):
            if stored["state"] != "COMPLETED":
                break
            result = StepResult(success=True, output=stored["output"] or "")
            results.append(result)
            observations.append(
                f"Tool {planned.tool_name} completed step {planned.id} "
                f"({planned.title}) successfully. Result: {result.output}")
        try:
            if not self.store.resolve_approval(run_id, step_id, accepted):
                raise LookupError("Approval is stale or was already resolved")
            self._emit(run_id, EventType.APPROVAL_RESOLVED, on_event,
                       {"accepted": accepted}, step_id)
            if not accepted:
                raise PermissionError(f"Approval denied for step {step_id}")
            self._transition(run_id, ExecutionState.EXECUTING, on_event)
            for index in range(step_index, len(plan.steps)):
                current = plan.steps[index]
                self._check_cancelled(cancel_event)
                if index > step_index and (
                        current.requires_approval
                        or current.tool_name in self.destructive_tools):
                    self._transition(
                        run_id, ExecutionState.AWAITING_APPROVAL, on_event)
                    message = f"{current.title}: {current.instruction}"
                    snapshot = self._append_snapshot(current, pending["working_directory"])
                    if snapshot is not None:
                        message += f"\nAPPEND_SHA256:{snapshot}\nAPPEND_CONTENT:{current.tool_args.get('content', current.tool_args.get('text'))}"
                    self.store.register_approval(
                        run_id, current.id, current.tool_name,
                        current.tool_args, message)
                    self._emit(
                        run_id, EventType.APPROVAL_REQUESTED, on_event,
                        {"message": message, "tool_name": current.tool_name,
                         "arguments": current.tool_args}, current.id)
                    return RunResult(
                        run_id=run_id, state=ExecutionState.AWAITING_APPROVAL,
                        plan=plan, steps=results)
                result = await self._run_step(
                    run_id, current, observations, cancel_event, on_event)
                results.append(result)
                if not result.success:
                    raise RuntimeError(result.error or f"Step {current.id} failed")
                observations.append(
                    f"Tool {current.tool_name} completed step {current.id} "
                    f"({current.title}) successfully. Result: {result.output}")
            task = pending["task"]
            self._transition(run_id, ExecutionState.VERIFYING, on_event)
            verification = await self._await_cancellable(
                self.backend.verify(task, plan, observations), cancel_event)
            self._emit(run_id, EventType.VERIFICATION_COMPLETED, on_event,
                       verification.model_dump(mode="json"))
            if not verification.success:
                raise RuntimeError(verification.summary or "Verification failed")
            response = await self._await_cancellable(
                self.backend.finalize(task, observations, verification),
                cancel_event)
            self._transition(run_id, ExecutionState.COMPLETED, on_event,
                             response=response)
            self._emit(run_id, EventType.FINAL_RESULT, on_event,
                       {"response": response})
            return RunResult(run_id=run_id, state=ExecutionState.COMPLETED,
                             response=response, plan=plan, steps=results)
        except asyncio.CancelledError:
            return self._cancel(run_id, plan, results, on_event)
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
            state = self._states[run_id]
            phase, event_type = self._failure_details(state)
            payload = {"error": message, "type": type(error).__name__,
                       "phase": phase}
            self._emit(run_id, event_type, on_event, payload)
            self._emit(run_id, EventType.ERROR, on_event, payload)
            self._transition(run_id, ExecutionState.FAILED, on_event,
                             error=message, failure_phase=phase)
            return RunResult(run_id=run_id, state=ExecutionState.FAILED,
                             error=message, failure_phase=phase,
                             plan=plan, steps=results)
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
                    if step.tool_name in {"edit_file", "replace_in_file", "write_binary_file"}:
                        raise PermissionError("Full-file replacement is disabled in Forge; use a reviewed incremental edit")
                    if step.tool_name == "create_file":
                        run = self.store.get_run(run_id)
                        path = step.tool_args.get("path")
                        if not isinstance(path, str) or not path.strip():
                            raise ValueError("create_file requires a concrete path")
                        target = Path(path).expanduser()
                        if not target.is_absolute():
                            target = Path(run["working_directory"]) / target
                        if target.exists():
                            raise FileExistsError(f"Forge cannot overwrite existing file: {target}")
                    if step.tool_name == "append_file":
                        run = self.store.get_run(run_id)
                        target = self._append_target(step, run["working_directory"])
                        content = step.tool_args.get("content", step.tool_args.get("text"))
                        with target.open("a", encoding="utf-8", newline="") as stream:
                            stream.write(content)
                        output = f"Appended {len(content)} characters to {target}"
                    else:
                        output = tool(**step.tool_args)
                    if inspect.isawaitable(output):
                        output = await self._await_cancellable(output, cancel_event)
                    success, output, tool_error = self._tool_result(output)
                    self._emit(run_id, EventType.TOOL_RESULT, on_event,
                               {"tool_name": step.tool_name, "success": success,
                                "output": output, "error": tool_error}, step.id)
                    if not success:
                        self.store.finish_step(
                            run_id, step.id, success=False, output=output,
                            error=tool_error)
                        result = StepResult(
                            success=False, output=output, error=tool_error)
                        self._emit(run_id, EventType.STEP_COMPLETED, on_event,
                                   result.model_dump(mode="json"), step.id)
                        return result
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
                if step.tool_name or attempt > self.max_retries:
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
                    error: str | None = None,
                    failure_phase: str | None = None) -> None:
        current = self._states[run_id]
        if state not in TRANSITIONS[current]:
            raise RuntimeError(f"Invalid agent transition: {current} -> {state}")
        self._states[run_id] = state
        self.store.set_state(run_id, state, response=response, error=error,
                             failure_phase=failure_phase)
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
    def _failure_details(state: ExecutionState) -> tuple[str, EventType]:
        if state is ExecutionState.PLANNING:
            return "planning", EventType.PLANNING_FAILED
        if state is ExecutionState.VERIFYING:
            return "verification", EventType.VERIFICATION_FAILED
        return "execution", EventType.EXECUTION_FAILED

    @staticmethod
    def _tool_result(value: Any) -> tuple[bool, str, str | None]:
        if value is False or value is None:
            return False, str(value), "Tool did not return a successful result"
        structured = value if isinstance(value, dict) else None
        output = (json.dumps(value, ensure_ascii=False) if isinstance(value, dict)
                  else str(value))
        if structured is None and isinstance(value, str):
            try:
                candidate = json.loads(value)
                if isinstance(candidate, dict):
                    structured = candidate
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        if structured is not None:
            status = str(structured.get("status", "")).casefold()
            exit_code = structured.get("exit_code")
            if status in {"denied", "error", "failed", "timeout", "cancelled"}:
                detail = (structured.get("error") or structured.get("stderr")
                          or structured.get("note") or status)
                return False, output, str(detail)
            if isinstance(exit_code, int) and exit_code != 0:
                detail = structured.get("stderr") or f"exit code {exit_code}"
                return False, output, str(detail)
        if output.lstrip().casefold().startswith("error:"):
            return False, output, output.strip()
        return True, output, None

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
