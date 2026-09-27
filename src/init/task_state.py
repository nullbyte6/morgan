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
"""Task contracts, evidence, obligations and explicit lifecycle transitions."""

import copy
import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path

from .task_effects import contains
from .task_outcomes import ActionResult, Outcome


def normalize_task_title(value):
    if not isinstance(value, str):
        return ""
    title = " ".join(value.split())
    if not 1 <= len(title.split()) <= 4:
        return ""
    if re.match(r"^(working on|currently|investigating|processing|trabajando|actualmente|investigando|procesando)\b",
                title, re.IGNORECASE):
        return ""
    return title


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def fingerprint(value):
    return hashlib.sha256(encoded(value).encode("utf-8")).hexdigest()


def control_rejection(reason, field, expected, *, requirements=None, code="invalid_checkpoint"):
    return {"accepted": False, "outcome": Outcome.REJECTED, "status": "rejected", "code": code,
            "reason": reason, "field": field, "expected": expected, "recoverable": True,
            "requirements": requirements or []}


class Lifecycle(StrEnum):
    ACTIVE = "active"
    COMPLETE = "complete"
    WAITING = "waiting"
    BLOCKED = "blocked"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"
    LIMIT_REACHED = "limit_reached"


@dataclass
class Criterion:
    verification: str
    resources: list[str]
    evidence: list[str] = field(default_factory=list)


@dataclass
class Evidence:
    id: str
    tool: str
    arguments: dict
    outcome: Outcome
    role: str
    sequence: int
    time: str
    revisions: dict
    effectful: bool
    digest: str
    result: object
    effects: list[str] = field(default_factory=list)
    verification_capable: bool = True

    @property
    def failed(self):
        return self.outcome not in {Outcome.SUCCESS, Outcome.NEGATIVE}


@dataclass
class Obligation:
    id: str
    action: str
    kind: str
    resources: list[str]
    sequence: int
    detail: str


@dataclass
class Dependency:
    obligation: str
    dependency: str
    evidence: list[str]
    required_change: str
    kind: str


@dataclass
class TaskState:
    objective: str
    title: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: Lifecycle = Lifecycle.ACTIVE
    kind: str | None = None
    role: str = "inspect"
    role_resources: list[str] = field(default_factory=list)
    criteria: dict[str, Criterion] = field(default_factory=dict)
    evidence: dict[str, Evidence] = field(default_factory=dict)
    obligations: dict[str, Obligation] = field(default_factory=dict)
    dependencies: list[Dependency] = field(default_factory=list)
    revisions: dict = field(default_factory=dict)
    changed_at: dict = field(default_factory=dict)
    decisions: list[str] = field(default_factory=list)
    strategy: str = ""
    notice: str = ""
    sequence: int = 0
    requests: int = 0
    inspections: dict = field(default_factory=dict)
    findings: dict = field(default_factory=dict)
    restrictions: dict = field(default_factory=dict)
    last_rejection: dict = field(default_factory=dict)
    output_recovery: dict = field(default_factory=dict)
    final_output: str | None = None
    trace: object = field(default=None, repr=False)

    def record(self, event, **details):
        if self.trace is not None:
            self.trace(event, **details)

    def refresh(self, revisions):
        changed = [resource for resource, revision in revisions.items()
                   if resource in self.revisions and self.revisions[resource] != revision]
        self.revisions.update(revisions)
        for resource in changed:
            self.changed_at[resource] = self.sequence
        for criterion in self.criteria.values():
            if any(contains(resource, dependency) or contains(dependency, resource)
                   for resource in changed for dependency in criterion.resources):
                criterion.evidence = []
        for inspection in self.inspections.values():
            if any(contains(resource, dependency) or contains(dependency, resource)
                   for resource in changed for dependency in inspection["resources"]):
                inspection["current"] = False
        return changed

    def observe(self, name, arguments, result, call_id, revisions, *, effectful=False,
                effects=(), uncertain=False, effect_scope=None, ancillary=False, verification_capable=None):
        if call_id in self.evidence:
            return self.evidence[call_id]
        self.sequence += 1
        self.refresh(revisions)
        affected = list(effect_scope if effect_scope is not None else revisions if uncertain else effects) if effectful else []
        item = Evidence(call_id, name, arguments, result.outcome, self.role, self.sequence,
                        datetime.now(timezone.utc).isoformat(), dict(revisions), effectful,
                        fingerprint(result.payload()), result.payload(), affected,
                        not effectful if verification_capable is None else verification_capable)
        self.evidence[call_id] = item
        if effectful and (effects or uncertain):
            for resource in affected:
                self.changed_at[resource] = self.sequence
            for criterion in self.criteria.values():
                if any(contains(resource, dependency) or contains(dependency, resource)
                       for resource in affected for dependency in criterion.resources):
                    criterion.evidence = []
            for inspection in self.inspections.values():
                if any(contains(resource, dependency) or contains(dependency, resource)
                       for resource in affected for dependency in inspection["resources"]):
                    inspection["current"] = False
            if not ancillary or any(contains(scope, resource) or contains(resource, scope)
                                    for criterion in self.criteria.values()
                                    for resource in criterion.resources for scope in affected):
                obligation_id = "effect:" + call_id
                self.obligations[obligation_id] = Obligation(
                    obligation_id, call_id, "reconcile" if uncertain else "verify", affected,
                    self.sequence, "Reconcile possible partial effects." if uncertain
                    else "Independently verify the resulting state.")
        if item.failed:
            self.restrictions[fingerprint({"tool": name, "arguments": arguments})] = {
                "tool": name, "arguments": arguments, "outcome": result.outcome,
                "code": result.code, "evidence": call_id, "resources": dict(revisions), "detail": result.data}
        self.record("observation", evidence=asdict(item), uncertain=uncertain)
        return item

    def valid_evidence(self, refs, resources, *, after=0, inspection=False):
        if not refs or len(set(refs)) != len(refs):
            return False
        observed = set()
        for ref in refs:
            item = self.evidence.get(ref)
            if item is None or item.failed or not item.verification_capable or (
                    not inspection and item.role != "verify") or item.sequence <= after:
                return False
            if item.effectful and (not resources or any(
                    contains(scope, resource) or contains(resource, scope)
                    for scope in item.effects for resource in resources)):
                return False
            relevant = {resource: revision for resource, revision in item.revisions.items()
                        if not resources or any(contains(resource, target) or contains(target, resource)
                                                for target in resources)}
            for resource, revision in relevant.items():
                if revision is None or self.revisions.get(resource) != revision or any(
                        (contains(scope, resource) or contains(resource, scope))
                        and sequence > item.sequence for scope, sequence in self.changed_at.items()):
                    return False
                observed.add(resource)
        return all(any(contains(scope, resource) for scope in observed) for resource in resources)

    def checkpoint(self, role, criteria, verification, completed, decisions, strategy,
                   resolutions, reopen, kind, resources, findings=()):
        def reject(reason, field="criteria", expected="A valid task contract"):
            return control_rejection(reason, field, expected)

        if self.status != Lifecycle.ACTIVE:
            return reject("Resume the task before updating its contract.")
        if role not in {"inspect", "execute", "verify"}:
            return reject("Unknown action role.")
        if kind not in {None, "read_only", "mutation"}:
            return reject("A supervised contract is read_only or mutation.")
        proposed_kind = kind or self.kind
        if proposed_kind is None:
            return reject("Declare read_only or mutation as the task kind.", "kind", ["read_only", "mutation"])
        if self.kind == "mutation" and proposed_kind != "mutation":
            return reject("A mutation contract cannot be weakened to read_only.")
        if any(not value.strip() for value in criteria) or len(set(criteria)) != len(criteria):
            return reject("Acceptance criteria must be distinct and nonempty.")
        proposed = copy.deepcopy(self.criteria)
        declared_resources = list(resources)
        for key, contract in verification.items():
            if not isinstance(contract, dict) or not isinstance(contract.get("method"), str) or not isinstance(contract.get("resources"), list):
                return reject("Verification entries must be keyed by the exact criterion, without a wrapper.",
                              "verification." + key, {"method": "Describe the observable check", "resources": []})
            declared_resources.extend(contract["resources"])
        if any(not isinstance(resource, str) or not (
                resource.startswith("domain:") and resource[7:].strip()
                or resource.startswith(("file:", "entry:")) and Path(resource.split(":", 1)[1]).is_absolute())
               for resource in declared_resources):
            return reject("Use resource identifiers, not bare paths, globs or display names.", "verification.resources",
                          ["file:" + str(Path.cwd() / "src" / "init" / "core.py"), "domain:presentation"])
        for criterion in criteria:
            contract = verification.get(criterion)
            if criterion not in proposed:
                if not contract or not contract.get("method", "").strip():
                    return reject("Each new criterion needs an explicit verification method and resource list.",
                                  "verification." + criterion, {"method": "Describe the observable check", "resources": []})
                proposed[criterion] = Criterion(contract["method"], list(contract.get("resources", [])))
            elif contract:
                if not contract["method"].strip() or not set(proposed[criterion].resources).issubset(contract["resources"]):
                    return reject("Retain existing verification dependencies when refining the method.")
                if contract["method"] != proposed[criterion].verification or contract["resources"] != proposed[criterion].resources:
                    proposed[criterion] = Criterion(contract["method"], list(contract["resources"]))
        if not proposed or set(verification) - set(proposed):
            return reject("Define criteria for the full objective; verification keys must name criteria.")
        if any(criterion not in proposed for criterion in reopen):
            return reject("Cannot reopen an unknown criterion.")
        for criterion in reopen:
            proposed[criterion].evidence = []
        for criterion, refs in completed.items():
            if criterion not in proposed or not self.valid_evidence(refs, proposed[criterion].resources,
                                                                  inspection=proposed_kind == "read_only"):
                return reject("Cite successful current observations covering the criterion's resources; effects need independent verification.",
                              "completed." + criterion, {"evidence_ids": "Successful current call IDs"})
            proposed[criterion].evidence = list(refs)
        obligations = copy.deepcopy(self.obligations)
        for obligation_id, resolution in resolutions.items():
            obligation = obligations.get(obligation_id)
            if obligation is None:
                return reject("Resolve only recorded effect obligations. Use completed for acceptance criteria.",
                              "resolutions." + obligation_id, {"known_obligations": list(obligations)})
            if not isinstance(resolution, dict) or obligation is None or not isinstance(resolution.get("finding"), str) or not resolution["finding"].strip() or not self.valid_evidence(
                    resolution.get("evidence", []), obligation.resources, after=obligation.sequence):
                return reject("Resolve each effect with a finding and subsequent verification of its resources.",
                              "resolutions." + obligation_id, {"finding": "Observed reconciliation", "evidence": []})
            del obligations[obligation_id]
        for index, finding in enumerate(findings):
            if not finding.get("finding", "").strip() or not self.valid_evidence(
                    finding.get("evidence", []), [], inspection=True):
                return reject("Findings require supporting successful current observations.",
                              f"findings.{index}", {"finding": "Observed fact", "evidence": []})
        self.kind = proposed_kind
        self.criteria = proposed
        self.obligations = obligations
        self.role = role
        self.role_resources = list(resources)
        self.decisions.extend(value for value in decisions if value not in self.decisions)
        self.strategy = strategy or self.strategy
        self.notice = ""
        self.last_rejection = {}
        for finding in findings:
            self.findings[fingerprint(finding)] = finding
        self.record("checkpoint", completed=completed, resolutions=resolutions, reopened=reopen)
        return {"accepted": True, "outcome": Outcome.SUCCESS, "status": "accepted", "ready_to_complete": self.complete(),
                "criteria": list(self.criteria)}

    def complete(self):
        return bool(self.kind and self.criteria and not self.obligations and not self.dependencies
                    and all(self.valid_evidence(value.evidence, value.resources, inspection=self.kind == "read_only")
                            for value in self.criteria.values()))

    def requirements(self):
        if self.kind == "direct":
            return []
        result = []
        if self.kind is None or not self.criteria:
            result.append({"code": "contract_required", "tool": "task_checkpoint", "fields": {
                "kind": "read_only or mutation", "phase": "inspect", "criteria": ["User outcome"],
                "verification": {"User outcome": {"method": "Observable check", "resources": []}}}})
        for name, criterion in self.criteria.items():
            if not self.valid_evidence(criterion.evidence, criterion.resources, inspection=self.kind == "read_only"):
                result.append({"code": "criterion_evidence_required", "criterion": name,
                               "method": criterion.verification, "resources": criterion.resources,
                               "evidence_ids": [ref for ref, item in self.evidence.items()
                                                if self.valid_evidence([ref], [], inspection=self.kind == "read_only")
                                                and (not criterion.resources or any(
                                                    contains(resource, target) or contains(target, resource)
                                                    for resource in item.revisions for target in criterion.resources))],
                               "repair": "Cite current evidence IDs in completed; read_only accepts inspection evidence."})
        result.extend({"code": "effect_verification_required", **asdict(value)} for value in self.obligations.values())
        result.extend({"code": "dependency_resolution_required", **asdict(value)} for value in self.dependencies)
        return result

    def recover_output(self, code, requirements):
        if self.status not in {Lifecycle.ACTIVE, Lifecycle.COMPLETE}:
            raise ValueError("Only executing or completed tasks can recover output.")
        self.status = Lifecycle.ACTIVE
        self.final_output = None
        self.output_recovery = {"code": code, "requirements": copy.deepcopy(requirements),
                                "delivery": {"tool": "task_finish", "field": "output",
                                             "expected": "A complete concise answer, or a summary with an artifact link"}}
        self.notice = "Repair the recorded requirements with control tools, then submit the answer through task_finish(output=...)."
        self.record("output_recovery", recovery=self.output_recovery)

    def can_finish_direct(self):
        return (self.kind in {None, "direct", "read_only"}
                and not (self.evidence or self.obligations or self.dependencies or self.inspections
                         or self.findings or self.restrictions or self.revisions or self.changed_at
                         or self.role_resources)
                and all(not (criterion.resources or criterion.evidence) for criterion in self.criteria.values()))

    def finish(self, direct=False, output=None):
        if self.status != Lifecycle.ACTIVE:
            return {"accepted": False, "reason": "Only active tasks can propose completion."}
        if (self.output_recovery or output is not None) and (not isinstance(output, str) or not output.strip()):
            return control_rejection("Submit a complete answer through task_finish during output recovery.", "output",
                                     "A nonempty complete answer, or a summary with an artifact link",
                                     requirements=self.requirements(), code="output_required")
        if direct and self.kind != "direct":
            if not self.can_finish_direct():
                return control_rejection("Direct answers cannot bypass a supervised task.", "direct", False,
                                         requirements=self.requirements(), code="completion_requirements")
            self.criteria = {}
            self.kind = "direct"
        elif self.kind != "direct" and not self.complete():
            return control_rejection("Satisfy the listed contract requirements before completion.", "completed",
                                     "Current evidence IDs keyed by exact criterion", requirements=self.requirements(),
                                     code="completion_requirements")
        self.status = Lifecycle.COMPLETE
        self.final_output = output
        self.output_recovery = {}
        self.record("complete", direct=direct)
        return {"accepted": True, "outcome": Outcome.SUCCESS, "status": self.status}

    def defer(self, kind, obligation, dependency, refs, required_change):
        if self.status != Lifecycle.ACTIVE or kind not in {"waiting", "blocked"}:
            return {"accepted": False, "reason": "Only an active task can propose waiting or blocking."}
        outstanding = obligation in self.obligations or (
            obligation in self.criteria and not self.criteria[obligation].evidence)
        if not outstanding or not dependency.strip() or not required_change.strip() or not refs:
            return {"accepted": False, "reason": "Identify an outstanding obligation, dependency, evidence and required change."}
        allowed = {Outcome.WAITING} if kind == "waiting" else {Outcome.EXTERNAL_BLOCKER}
        observations = [self.evidence.get(ref) for ref in refs]
        typed_dependency = any(item is not None and item.outcome in allowed
                               and item.result.get("dependency") == dependency for item in observations)
        observed_constraint = kind == "blocked" and all(
            item is not None and not item.failed and not item.effectful for item in observations)
        if any(item is None for item in observations) or not (typed_dependency or observed_constraint):
            return {"accepted": False, "reason": "Dependency requires a typed supporting observation; repetition and generic failures are not blockers."}
        if any(revision is None or self.revisions.get(resource) != revision
               for item in observations for resource, revision in item.revisions.items()):
            return {"accepted": False, "reason": "Dependency evidence is stale or its resource state is unknown."}
        self.dependencies = [Dependency(obligation, dependency, list(refs), required_change, kind)]
        self.status = Lifecycle(kind)
        self.notice = f"{kind}: {dependency}. {required_change}"
        self.record(kind, dependency=asdict(self.dependencies[0]))
        return {"accepted": True, "status": self.status}

    def suspend(self, status, reason):
        if status not in {Lifecycle.INTERRUPTED, Lifecycle.CANCELLED, Lifecycle.LIMIT_REACHED}:
            raise ValueError("Unsupported suspension transition.")
        self.status = status
        self.notice = reason
        self.record(status, reason=reason)

    def resume(self):
        if self.status not in {Lifecycle.INTERRUPTED, Lifecycle.WAITING, Lifecycle.BLOCKED,
                               Lifecycle.LIMIT_REACHED}:
            raise ValueError("Task is not resumable.")
        self.status = Lifecycle.ACTIVE
        self.notice = "Preserved task resumed. Recheck recorded dependencies before clearing them."
        self.record("resumed")

    def resolve_dependency(self, refs, finding):
        if not self.dependencies or not finding.strip():
            return {"accepted": False, "reason": "No dependency or missing resolution finding."}
        supporting = [self.evidence[ref] for entry in self.dependencies for ref in entry.evidence]
        after = max(item.sequence for item in supporting)
        user_input = bool(refs) and all(
            ref in self.evidence and self.evidence[ref].tool == "user_input"
            and self.evidence[ref].sequence > after for ref in refs) and all(
                item.kind == "waiting" and item.dependency == "user_input" for item in self.dependencies)
        if not user_input and not self.valid_evidence(refs, list({
                resource for item in supporting for resource in item.revisions}), after=after):
            return {"accepted": False, "reason": "Reobserve the dependency before resolving it."}
        self.dependencies = []
        self.record("dependency_resolved", evidence=refs, finding=finding, user_input=user_input)
        return {"accepted": True}

    def snapshot(self, include_results=False, include_evidence=True):
        evidence = []
        for item in self.evidence.values() if include_evidence else ():
            value = asdict(item)
            if not include_results:
                value.pop("result")
                value.pop("arguments")
            evidence.append(value)
        snapshot = {"id": self.id, "objective": self.objective, "title": self.title, "status": self.status,
                "contract": self.kind, "role": self.role, "role_resources": self.role_resources,
                "criteria": {key: asdict(value) for key, value in self.criteria.items()},
                "obligations": {key: asdict(value) for key, value in self.obligations.items()},
                "dependencies": [asdict(item) for item in self.dependencies],
                "revisions": self.revisions, "changed_at": self.changed_at,
                "strategy": self.strategy, "decisions": self.decisions, "notice": self.notice,
                "sequence": self.sequence, "requests": self.requests, "inspections": self.inspections,
                "findings": self.findings, "restrictions": self.restrictions,
                "last_rejection": self.last_rejection, "pending_verification": self.requirements(),
                "direct_answer_allowed": self.can_finish_direct(),
                "output_recovery": copy.deepcopy(self.output_recovery), "final_output": self.final_output}
        if include_evidence:
            snapshot["evidence"] = evidence
        return snapshot
