"""Per-turn supervision for the existing Pydantic agent and tool registry."""

import asyncio
import copy
import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.exceptions import ToolFailed
from pydantic_ai.messages import ModelRequest, ModelMessagesTypeAdapter, UserPromptPart
from pydantic_ai.toolsets import FunctionToolset

from src.init.self_code import get_repo_state

def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def fingerprint(value):
    return hashlib.sha256(encoded(value).encode("utf-8")).hexdigest()


def information_units(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            pass
    if value is None:
        return set()
    if isinstance(value, dict):
        return {fingerprint((key, unit)) for key, item in value.items()
                for unit in information_units(item)}
    if isinstance(value, (list, tuple)):
        return {unit for item in value for unit in information_units(item)}
    units = set()
    for line in str(value).splitlines():
        words = re.findall(r"\w+", line.casefold())
        width = min(4, len(words))
        if width:
            units.update(fingerprint(words[index:index + width])
                         for index in range(len(words) - width + 1))
    return units


def failed_result(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return value.strip().casefold().startswith((
                "error:", "error ", "failed:", "denied", "cancelled",
                "canceled", "inspection_budget_exhausted"))
    if isinstance(value, dict):
        return (bool(value.get("error")) or value.get("success") is False
                or value.get("status") in ("error", "failed", "denied", "timeout", "cancelled")
                or value.get("exit_code", 0) not in (0, None))
    return False

INSPECTION_TOOLS = frozenset({
    "get_repo",
    "list_code",
    "search_code",
    "read_code",
})

MUTATION_TOOLS = frozenset({
    "edit_code",
})

@dataclass
class Evidence:
    id: str
    tool: str
    arguments: str
    digest: str
    phase: str
    failed: bool
    sequence: int
    preview: str


@dataclass
class TaskState:
    objective: str
    phase: str = "inspect"
    status: str = "active"
    criteria: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)
    decisions: list = field(default_factory=list)
    changes: list = field(default_factory=list)
    unresolved: set = field(default_factory=set)
    seen: set = field(default_factory=set)
    information_seen: set = field(default_factory=set)
    used_evidence: set = field(default_factory=set)
    sequence: int = 0
    requests: int = 0
    last_progress: int = 0
    last_change: int = 0
    stagnant: int = 0
    recovery_at: int | None = None
    recovery_offered_at: int | None = None
    recovery_started_at: int | None = None
    recovery_sequence: int = 0
    strategy: str = ""
    recovery_strategy: str = ""
    notice: str = ""
    last_progress_request: int = 0
    tool_attempts: int = 0
    information_gain_ratio: float = 0.2
    trace: object = field(default=None, repr=False)
    milestones: list = field(default_factory=list)

    def record(self, event, **details):
        if self.trace is not None:
            self.trace(event, **details)

    def mark_progress(self):
        self.last_progress = self.sequence
        self.last_progress_request = self.requests
        self.stagnant = 0
        self.recovery_at = None
        self.recovery_offered_at = None
        self.recovery_started_at = None
        self.notice = ""

    def add_milestone(self, kind, value, evidence=()):
        evidence = tuple(sorted(set(evidence)))
        signature = (kind, fingerprint(value), evidence)

        if signature in {
            (item["kind"], item["fingerprint"], tuple(item["evidence"]))
            for item in self.milestones
        }:
            return False

        self.milestones.append({
            "kind": kind,
            "fingerprint": fingerprint(value),
            "value": value,
            "evidence": list(evidence),
            "sequence": self.sequence,
        })
        self.mark_progress()
        self.record(
            "milestone",
            kind=kind,
            value=value,
            evidence=list(evidence))
        return True

    def observe(self,name, arguments, result, call_id, failed=False,
        state_changed=False):
        result = getattr(result, "return_value", result)
        self.sequence += 1
        digest = fingerprint(result)
        key = (name, fingerprint(arguments), digest)
        novel = key not in self.seen and (name, digest) not in self.seen
        self.seen.update((key, (name, digest)))
        failed = failed or failed_result(result)
        units = information_units(result) if not failed else set()
        gained = units - self.information_seen
        information_progress = bool(gained) and len(gained) / len(units) >= self.information_gain_ratio
        if not failed:
            self.information_seen.update(units)
        item = Evidence(call_id, name, encoded(arguments), digest, self.phase,
                        failed, self.sequence, str(result)[:700])
        self.evidence[call_id] = item

        changed = state_changed and not failed

        if changed:
            self.last_change = self.sequence
            self.changes.append(call_id)
            self.status = "active"
            self.add_milestone(
                "state_change",
                {
                    "tool": name,
                    "arguments": arguments,
                    "digest": digest,
                },
                evidence=(call_id,))
            self.phase = "verify"

        if failed and name in MUTATION_TOOLS:
            self.unresolved.add(call_id)

        if self.phase == "inspect":
            self.stagnant = 0 if information_progress else self.stagnant + 1
        else:
            self.stagnant = 0 if novel and not failed else self.stagnant + 1
        self.record(
            "observation",
            call_id=call_id,
            tool=name,
            arguments=arguments,
            result=result,
            failed=failed,
            novel=novel,
            changed=changed,
            units=len(units),
            gained=len(gained),
            information_progress=information_progress,
            progress_accepted=changed,
            reason=(
                "failed"
                if failed
                else "state_changed"
                if changed
                else "new_inspection_evidence"
                if self.phase == "inspect" and information_progress
                else "insufficient_information_gain"
                if self.phase == "inspect"
                else "awaiting_verified_checkpoint"))
        self.assess()
        return item

    def assess(self, *, allow_block=False):
        self.record(
            "assessment",
            allow_block=allow_block,
            stagnant=self.stagnant,
            last_progress=self.last_progress,
            last_progress_request=self.last_progress_request)

        if self.status != "active":
            return

        if self.stagnant < 3:
            return

        if self.recovery_at is None:
            self.recovery_at = self.requests
            self.notice = (
                "Inspection is repeating previously observed information. "
                "Do not repeat equivalent tool calls. Reuse existing evidence, "
                "update the task checkpoint, and complete or narrow the remaining criteria.")
            
            self.record(
                "recovery_requested",
                stagnant=self.stagnant,
                requests=self.requests,
                sequence=self.sequence)

    def checkpoint(self, phase, criteria, completed, decisions, strategy, resolves):
        if self.status == "blocked":
            return {"accepted": False, "reason": self.notice}
        
        if any(not criterion.strip() for criterion in criteria) or len(set(criteria)) != len(criteria):
            return {"accepted": False, "reason": "Acceptance criteria must be distinct and nonempty."}
        if not self.criteria:
            if not criteria:
                return {"accepted": False, "reason": "Define acceptance criteria for the full user objective."}
            self.criteria = {criterion: [] for criterion in criteria}
        elif criteria and not set(self.criteria).issubset(criteria):
            return {"accepted": False, "reason": "Retain the original acceptance criteria; do not weaken the goal."}
        for criterion in criteria:
            self.criteria.setdefault(criterion, [])
        proposed = dict(self.criteria)
        new_refs = set()
        for criterion, refs in completed.items():
            if criterion not in proposed or not refs:
                return {"accepted": False, "reason": "Unknown criterion or missing verification evidence."}
            for ref in refs:
                evidence = self.evidence.get(ref)

                if evidence is None or evidence.failed:
                    return {
                        "accepted": False,
                        "reason": "Use successful tool evidence to verify completed criteria.",
                    }

                if self.last_change:
                    if (
                        evidence.phase != "verify"
                        or evidence.sequence < self.last_change):
                        return {
                            "accepted": False,
                            "reason": (
                                "After execution, verification must use successful "
                                "verification evidence collected after the latest change."
                            )}
            proposed[criterion] = refs
            new_refs.update(refs)
        if resolves and (not new_refs or any(ref not in self.unresolved for ref in resolves)):
            return {"accepted": False, "reason": "Resolve observed errors with fresh verification evidence."}
        if any(not any(self.evidence[verified].sequence > self.evidence[failed].sequence
                       for verified in new_refs) for failed in resolves):
            return {"accepted": False, "reason": "Error resolution requires verification after the failure."}
        change = self.evidence.get(self.changes[-1]) if self.changes else None
        signatures = {(criterion, self.evidence[ref].digest,
                       (change.tool, change.arguments, change.digest) if change else None)
                      for criterion, refs in completed.items() for ref in refs
                      if not self.criteria[criterion] or any(
                          self.evidence[old].sequence < self.last_change
                          for old in self.criteria[criterion])}

        if decisions and not self.evidence:
            return {
                "accepted": False,
                "reason": "Decisions require collected tool evidence.",
            }

        new_decisions = [
            value for value in decisions
            if value not in self.decisions
        ]

        self.criteria = proposed
        self.unresolved.difference_update(resolves)
        self.used_evidence.update(signatures)
        self.decisions.extend(new_decisions)
        self.strategy = strategy or self.strategy
        self.phase = phase

        self.unresolved.difference_update({
            ref
            for ref in self.unresolved
            if self.evidence[ref].tool == "task_checkpoint"
        })

        for decision in new_decisions:
            self.add_milestone(
                "decision",
                decision,
                evidence=new_refs)

        for criterion, refs in completed.items():
            if refs:
                self.add_milestone(
                    "criterion_verified",
                    criterion,
                    evidence=refs)

        if resolves:
            self.add_milestone(
                "errors_resolved",
                sorted(resolves),
                evidence=new_refs)

    def complete(self):
        if self.phase != "verify" or not self.criteria or self.unresolved:
            return False

        for refs in self.criteria.values():
            if not refs:
                return False

            for ref in refs:
                evidence = self.evidence.get(ref)

                if evidence is None or evidence.failed:
                    return False

                if self.last_change and (
                    evidence.phase != "verify"
                    or evidence.sequence < self.last_change):
                    return False

        return True

    def snapshot(self):
        return {
            "objective": self.objective,
            "phase": self.phase,
            "status": self.status,
            "criteria": self.criteria,
            "decisions": self.decisions,
            "milestones": self.milestones[-12:],
            "changes": self.changes,
            "unresolved": sorted(self.unresolved),
            "strategy": self.strategy,
            "notice": self.notice,
            "evidence": [
                {**vars(value), "arguments": value.arguments[:700]}
                for value in list(self.evidence.values())[-12:]
            ],
        }


class TaskStopped(Exception):
    pass


class TaskControl(AbstractCapability):
    def __init__(self, objective, context, cancel_event, on_progress=None):
        super().__init__()
        self.state = TaskState(objective)
        self.context = context
        self.trace_path = context.directory / f"task-control-{uuid.uuid4().hex}.jsonl"
        self.state.trace = self.trace
        self.cancel_event = cancel_event
        self.on_progress = on_progress
        self.messages = []
        self.artifacts = {}
        self.last_notice = ""
        self.tool_lock = asyncio.Lock()
        self.context_characters = 48000
        self.toolset = FunctionToolset()
        self.toolset.add_function(self.task_checkpoint, sequential=True)
        self.trace("start")

    def trace(self, event, **details):
        state = {key: value for key, value in vars(self.state).items()
                 if key not in ("trace", "seen", "information_seen", "used_evidence", "evidence")}
        state["unresolved"] = sorted(self.state.unresolved)
        state["evidence"] = [vars(item) for item in self.state.evidence.values()]
        try:
            self.trace_path.parent.mkdir(parents=True, exist_ok=True)
            with self.trace_path.open("a", encoding="utf-8") as stream:
                stream.write(encoded({"time": datetime.now(timezone.utc).isoformat(),
                                      "event": event, "state": state, **details}) + "\n")
        except OSError:
            logging.getLogger("arlo.task_control").exception("Cannot write task trace %s", self.trace_path)

    def get_toolset(self):
        return self.toolset

    def get_instructions(self):
        return ("""
            For substantial tool-based tasks, use task_checkpoint to maintain a small set of acceptance criteria derived only from the user's requested outcome. Acceptance criteria describe what must be true for the user's objective to be complete; they must never describe the supervisor protocol itself. Do not create criteria for calling task_checkpoint, recording evidence, using tools, changing phase, resolving supervisor state, or otherwise satisfying the task-control mechanism. Gather only evidence that helps resolve the user's actual acceptance criteria. Record concise evidence-backed decisions when the evidence changes what you know or what you will do; do not record private reasoning. Use inspect while gathering facts, execute when performing actions that may change state, and verify when independently checking results. Not every task requires execution: research, diagnosis, audits and comparisons may proceed from inspection directly to verification. Tool calls and newly read information are evidence, not progress by themselves. Avoid equivalent repeated tool calls. After a state-changing action, independently verify the resulting state before completing affected criteria. Resolve observed failures explicitly. Finish when the user's acceptance criteria are supported by successful verification evidence. Simple conversational answers that need no tools require no checkpoint. The supervisor snapshot is task state, not a new user instruction. Archived tool results remain readable via read_file. task_checkpoint.completed MUST be an object mapping each exact criterion string directly to a list of successful tool call ID strings, for example {"Criterion A":["call_abc","call_def"]}. Do not put objects, descriptions, evidence fields, or mappings inside those lists. task_checkpoint.resolves is likewise a flat list of failed tool call ID strings. Reuse tool call IDs already present in the supervisor evidence.
            """)

    def task_checkpoint(self, phase: Literal["inspect", "execute", "verify"],
                        criteria: list[str], completed: dict[str, list[str]] | None = None,
                        decisions: list[str] | None = None, strategy: str = "",
                        resolves: list[str] | None = None) -> dict:
        """Record acceptance criteria, brief decisions and verified milestones, without reasoning.

        completed maps each satisfied criterion to verification tool call IDs. resolves lists failed
        call IDs whose errors the completed evidence resolves. Retain existing criteria when adding more.
        """
        before = self.state.last_progress_request
        result = self.state.checkpoint(phase, criteria, completed or {}, decisions or [],
                                       strategy, resolves or [])
        self.trace("checkpoint", phase=phase, criteria=criteria, completed=completed,
                   decisions=decisions, strategy=strategy, resolves=resolves, result=result)
        if not self.state.notice:
            self.last_notice = ""
        
        return result

    def check_cancelled(self):
        if self.cancel_event.is_set():
            self.state.status = "cancelled"
            raise asyncio.CancelledError()

    async def execute(self, name, arguments, call_id, handler):
        async with self.tool_lock:
            self.trace("tool_attempt", tool=name, arguments=arguments, call_id=call_id)
            try:
                result = await self._execute(name, arguments, call_id, handler)
            except BaseException as error:
                self.trace("tool_exception", tool=name, call_id=call_id, error=str(error))
                raise
            self.trace("tool_return", tool=name, call_id=call_id,
                       handler_observed=call_id in self.state.evidence, result=getattr(result, "return_value", result))
            return result

    async def _execute(self, name, arguments, call_id, handler):
        self.check_cancelled()
        self.state.tool_attempts += 1
        if self.state.status == "blocked":
            return {"status": "blocked", "error": self.state.notice}
        
        if name == "task_checkpoint":
            return await handler(arguments)

        if name in INSPECTION_TOOLS:
            argument_fingerprint = fingerprint(arguments)

            duplicate = next((
                evidence
                for evidence in self.state.evidence.values()
                if evidence.tool == name
                and fingerprint(json.loads(evidence.arguments)) == argument_fingerprint
                and not evidence.failed), None,)

            if duplicate is not None:
                self.trace(
                    "duplicate_inspection_rejected",
                    tool=name,
                    arguments=arguments,
                    call_id=call_id,
                    existing_call_id=duplicate.id,
                )

                return {
                    "status": "already_observed",
                    "evidence_id": duplicate.id,
                    "note": (
                        f"Equivalent inspection evidence already exists as {duplicate.id}. "
                        "Reuse that evidence in task_checkpoint instead of repeating "
                        "or rephrasing this inspection."
                    ),
                }
        
        if self.state.status == "complete":
            return {"status": "complete", "note": "All criteria are verified. Return the final answer."}

        if self.state.recovery_offered_at is not None and self.state.recovery_started_at is None:
            self.state.recovery_started_at = self.state.requests
            self.state.recovery_sequence = self.state.sequence
            self.trace("recovery_execution_started", tool=name, call_id=call_id)
        self.trace("tool_handler_started", tool=name, call_id=call_id)
        before_state = get_repo_state() if name in MUTATION_TOOLS else None

        result = await handler(arguments)

        after_state = get_repo_state() if before_state is not None else None
        state_changed = (
            before_state is not None
            and after_state is not None
            and before_state != after_state)

        if before_state is not None:
            self.trace(
                "mutation_probe",
                tool=name,
                call_id=call_id,
                state_changed=state_changed)

        self.state.observe(
            name,
            arguments,
            result,
            call_id,
            state_changed=state_changed)
        
        self.check_cancelled()
        return result

    async def wrap_tool_execute(self, ctx, *, call, tool_def, args, handler):
        return await self.execute(call.tool_name, args, call.tool_call_id, handler)

    async def on_tool_execute_error(self, ctx, *, call, tool_def, args, error):
        result = {"status": "error", "error": str(error),
                  "note": "Execution may be partial. Inspect state before changing strategy or retrying."}
        self.state.observe(call.tool_name, args, result, call.tool_call_id, failed=True)
        return result

    async def on_tool_validate_error(self, ctx, *, call, tool_def, args, error):
        if call.tool_name == "task_checkpoint":
            self.trace(
                "checkpoint_validation_error",
                call_id=call.tool_call_id,
                arguments=args,
                error=str(error),
            )

            raise ToolFailed(""" 
                Invalid task_checkpoint arguments. completed must map exact criterion strings directly to lists of successful tool call ID strings, for example "
                '{"Criterion A":["call_abc","call_def"]}. ' resolves must be a flat list of failed tool call ID strings. Correct only the checkpoint call. Do not repeat inspection.""")

        self.state.tool_attempts += 1
        self.state.observe(
            call.tool_name,
            args,
            str(error),
            call.tool_call_id,
            failed=True,
        )
        raise ToolFailed(str(error))

    def archive(self, raw, label):
        key = fingerprint(raw)
        if key not in self.artifacts:
            self.artifacts[key] = self.context._store(raw, ".json", label)
        return self.artifacts[key]

    def compact(self, messages):
        result = copy.deepcopy(messages)
        for message in result:
            for part in message.parts:
                if part.part_kind == "tool-return":
                    raw = encoded(part.content)
                    if len(raw) > 4096:
                        part.content = (raw[:1200] + "\nFull evidence: "
                                        + self.archive(raw, f"Evidence {part.tool_call_id}"))
        raw = ModelMessagesTypeAdapter.dump_json(result).decode()
        if len(raw) <= self.context_characters:
            return result
        pending = set()
        boundaries = []
        responded = False
        for index, message in enumerate(result):
            responded = responded or message.kind == "response"
            for part in message.parts:
                if part.part_kind == "tool-call":
                    pending.add(part.tool_call_id)
                elif part.part_kind in ("tool-return", "retry-prompt"):
                    pending.discard(getattr(part, "tool_call_id", None))
            if not pending and responded:
                boundaries.append(index + 1)
        for boundary in boundaries:
            suffix = result[boundary:]
            if len(ModelMessagesTypeAdapter.dump_json(suffix)) <= self.context_characters // 2:
                archive = self.archive(ModelMessagesTypeAdapter.dump_json(
                    result[:boundary]).decode(), "Earlier conversation and tool evidence")
                self.trace("context_compacted", archived_messages=boundary,
                           retained_messages=len(suffix), archive=archive,
                           archived_tool_calls=[part.tool_call_id for message in result[:boundary]
                                                for part in message.parts if part.part_kind == "tool-return"])
                return [ModelRequest(parts=[UserPromptPart(
                    "Earlier context archived without discarding evidence: " + archive)]), *suffix]
        return result

    async def before_model_request(self, ctx, request_context):
        self.check_cancelled()
        self.messages = ctx.messages
        self.state.requests += 1
        self.trace("before_model_request")
        self.state.assess(allow_block=True)
        if self.state.status == "blocked":
            raise TaskStopped(self.state.notice)
        if self.state.recovery_at is not None and self.state.recovery_offered_at is None:
            self.state.recovery_offered_at = self.state.requests
            self.state.recovery_sequence = self.state.sequence
        if not self.state.notice:
            self.last_notice = ""
        if self.state.notice and self.last_notice != self.state.notice:
            self.last_notice = self.state.notice
            
        messages = [message for message in request_context.messages
                    if not (message.metadata or {}).get("arlo_task_snapshot")]
        messages = self.compact(messages)
        snapshot_data = self.state.snapshot()
        snapshot = encoded(snapshot_data)
        if len(snapshot) > 16000:
            snapshot_data = {"objective": self.state.objective, "phase": self.state.phase,
                             "status": self.state.status, "notice": self.state.notice,
                             "task_ledger": self.archive(snapshot, "Full task ledger"),
                             "recent_evidence": snapshot_data["evidence"][-4:]}
            snapshot = encoded(snapshot_data)
        from src.init.self_code import INSPECTION_TOOLS, compact_inspection_context
        previews = snapshot_data.get("evidence", snapshot_data.get("recent_evidence", []))
        inspection = compact_inspection_context(
            messages, self.archive,
            sum(len(item["preview"]) for item in previews if item["tool"] in INSPECTION_TOOLS))
        self.trace("inspection_context", **inspection)
        messages.append(ModelRequest(parts=[UserPromptPart("Supervisor task state: " + snapshot)],
                                     metadata={"arlo_task_snapshot": True}))
        request_context.messages = messages
        self.trace("request_ready", supervisor_snapshot=snapshot)
        return request_context

    async def after_model_request(self, ctx, *, request_context, response):
        self.trace("model_response", model=response.model_name, finish_reason=response.finish_reason,
                   parts=[vars(part) for part in response.parts
                          if part.part_kind in ("text", "tool-call")], usage=vars(response.usage))
        return response

    def accept_output(self):
        self.check_cancelled()
        self.trace("output_assessment", accepted=(not self.state.criteria and not self.state.tool_attempts)
                   or self.state.complete())
        if not self.state.criteria and not self.state.tool_attempts:
            self.state.status = "complete"
            return True
        if self.state.complete():
            self.state.status = "complete"
            return True
        return False
