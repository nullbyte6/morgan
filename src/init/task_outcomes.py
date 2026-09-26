"""Machine-readable action results and conservative adapters for legacy tools."""

import json
from dataclasses import asdict, dataclass, is_dataclass
from enum import StrEnum


class Outcome(StrEnum):
    SUCCESS = "success"
    NEGATIVE = "negative"
    REJECTED = "rejected"
    FAILED = "failed"
    WAITING = "waiting"
    CANCELLED = "cancelled"
    UNCERTAIN = "uncertain"
    EXTERNAL_BLOCKER = "external_blocker"


@dataclass(frozen=True)
class ActionResult:
    outcome: Outcome
    data: object = None
    code: str = ""
    dependency: str = ""
    required_change: str = ""

    @property
    def successful(self):
        return self.outcome in (Outcome.SUCCESS, Outcome.NEGATIVE)

    def payload(self):
        return asdict(self)


def normalize_result(value, *, text_observation=False):
    value = getattr(value, "return_value", value)
    if isinstance(value, ActionResult):
        return value
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    elif is_dataclass(value):
        value = asdict(value)
    parsed = value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return ActionResult(Outcome.SUCCESS if text_observation else Outcome.UNCERTAIN,
                                value, "legacy_observation" if text_observation else "untyped_result")
    if isinstance(parsed, dict):
        if "outcome" in parsed:
            try:
                outcome = Outcome(parsed["outcome"])
            except (ValueError, TypeError):
                return ActionResult(Outcome.UNCERTAIN, parsed, "invalid_outcome")
            return ActionResult(outcome, parsed.get("data"), parsed.get("code", ""),
                                parsed.get("dependency", ""), parsed.get("required_change", ""))
        status = parsed.get("status")
        if status in {"needs_input", "permission_required", "input_required", "denied"}:
            return ActionResult(Outcome.WAITING, parsed, str(status),
                                "permission" if status in {"denied", "permission_required"} else "user_input",
                                "Provide the required permission or input.")
        if status in {"cancelled", "canceled"}:
            return ActionResult(Outcome.CANCELLED, parsed, str(status))
        if status in {"unavailable", "blocked"} and parsed.get("dependency") and parsed.get("required_change"):
            return ActionResult(Outcome.EXTERNAL_BLOCKER, parsed, str(status),
                                parsed["dependency"], parsed["required_change"])
        if status in {"partial", "unknown", "running", "timeout"}:
            return ActionResult(Outcome.UNCERTAIN, parsed, str(status))
        if parsed.get("error") or status in {"error", "failed"} or any(
                parsed.get(key) is False for key in ("ok", "success", "accepted")) or (
                parsed.get("exit_code") not in (None, 0)):
            return ActionResult(Outcome.FAILED, parsed, "legacy_failure")
        if status in {"not_found", "no_matches", "empty"}:
            return ActionResult(Outcome.NEGATIVE, parsed, str(status))
        return ActionResult(Outcome.SUCCESS, parsed, "structured_result")
    if text_observation:
        return ActionResult(Outcome.SUCCESS, value, "legacy_observation")
    return ActionResult(Outcome.UNCERTAIN, value, "untyped_result")
