"""Regression contracts for deterministic task supervision, without model or UI services."""

import ast
import copy
import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from src.init.task_effects import TOOL_SPECS, content_revision, file_resource
from src.init.task_outcomes import ActionResult, Outcome, normalize_result
from src.init.task_state import Lifecycle, TaskState


class TaskStateTests(unittest.TestCase):
    def setUp(self):
        self.state = TaskState("Deliver the requested outcome")
        self.resource = "domain:subject"
        self.contract("read_only", {"A": [self.resource]})

    def contract(self, kind, criteria):
        return self.state.checkpoint("inspect", list(criteria), {
            name: {"method": "Independent observation of the requested outcome", "resources": resources}
            for name, resources in criteria.items()}, {}, [], "", {}, [], kind, [])

    def observe(self, call_id, outcome=Outcome.SUCCESS, resource=None, revision="1", effectful=False,
                effects=(), uncertain=False, dependency=""):
        return self.state.observe("observer" if not effectful else "mutation", {},
                                  ActionResult(outcome, {"observed": True}, dependency=dependency), call_id,
                                  {resource or self.resource: revision}, effectful=effectful,
                                  effects=effects, uncertain=uncertain)

    def checkpoint(self, **changes):
        arguments = dict(role="verify", criteria=[], verification={}, completed={}, decisions=[],
                         strategy="", resolutions={}, reopen=[], kind=None, resources=[])
        arguments.update(changes)
        return self.state.checkpoint(**arguments)

    def test_inspection_count_overlap_and_novelty_have_no_lifecycle_authority(self):
        for index in range(100):
            self.observe(str(index))
            self.assertEqual(self.state.status, Lifecycle.ACTIVE)
        self.assertFalse(self.state.complete())
        self.assertNotIn("stagnant", self.state.snapshot())

    def test_negative_search_is_valid_observation_and_not_completion(self):
        item = self.observe("negative", Outcome.NEGATIVE)
        self.assertFalse(item.failed)
        self.assertEqual(self.state.status, Lifecycle.ACTIVE)
        self.assertFalse(self.state.finish()["accepted"])

    def test_missing_contract_cannot_complete_or_become_direct_after_actions(self):
        state = TaskState("Implement a feature")
        state.observe("read_code", {}, ActionResult(Outcome.SUCCESS, "source"), "read", {})
        self.assertFalse(state.finish()["accepted"])
        self.assertFalse(state.finish(direct=True)["accepted"])

    def test_direct_conversation_is_explicit_and_action_free(self):
        state = TaskState("Hello")
        self.assertTrue(state.finish(direct=True)["accepted"])
        self.assertEqual(state.kind, "direct")
        self.assertEqual(state.status, Lifecycle.COMPLETE)

    def test_read_only_contract_completes_without_mutation(self):
        self.state.role = "verify"
        self.observe("verified")
        self.assertTrue(self.checkpoint(completed={"A": ["verified"]})["accepted"])
        self.assertTrue(self.state.finish()["accepted"])

    def test_inspection_requires_explicit_verification_before_completion(self):
        self.observe("read")
        self.assertFalse(self.checkpoint(completed={"A": ["read"]})["accepted"])

    def test_registry_has_explicit_effect_declarations(self):
        tree = ast.parse(Path(__file__).with_name("tools.py").read_text(encoding="utf-8"))
        registry = next(node for node in tree.body if isinstance(node, ast.Assign)
                        and any(isinstance(target, ast.Name) and target.id == "TOOLS" for target in node.targets))
        names = {node.id for node in registry.value.elts}
        self.assertEqual(names | {"read_attachment"}, set(TOOL_SPECS))
        for name in ("edit_code", "create_code", "create_file", "delete_file", "execute_command",
                     "git_push", "update_config", "send_email", "run_quick_command", "install_app"):
            self.assertTrue(TOOL_SPECS[name].effectful)

    def test_already_dirty_and_untracked_file_contents_have_distinct_revisions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "source.py")
            path.write_text("a = 1", encoding="utf-8")
            resource = file_resource(path)
            first = content_revision(resource)
            path.write_text("a = 2", encoding="utf-8")
            second = content_revision(resource)
            path.write_text("a = 3", encoding="utf-8")
            third = content_revision(resource)
            self.assertEqual(len({first, second, third}), 3)

    def test_partial_effect_creates_reconciliation_obligation(self):
        self.observe("partial", Outcome.FAILED, effectful=True, uncertain=True)
        self.assertEqual(self.state.obligations["effect:partial"].kind, "reconcile")
        self.assertFalse(self.state.complete())

    def test_mutation_success_cannot_verify_itself(self):
        self.state.role = "verify"
        self.observe("write", effectful=True, effects=[self.resource])
        self.assertFalse(self.checkpoint(completed={"A": ["write"]})["accepted"])

    def test_mutation_reopens_affected_criterion_and_preserves_unrelated_evidence(self):
        self.contract("mutation", {"A": [self.resource], "B": ["domain:other"]})
        self.state.role = "verify"
        self.observe("a")
        self.observe("b", resource="domain:other")
        self.assertTrue(self.checkpoint(completed={"A": ["a"], "B": ["b"]})["accepted"])
        self.observe("write", revision="2", effectful=True, effects=[self.resource])
        self.assertEqual(self.state.criteria["A"].evidence, [])
        self.assertEqual(self.state.criteria["B"].evidence, ["b"])
        self.observe("a2", revision="2")
        self.assertTrue(self.checkpoint(completed={"A": ["a2"]}, resolutions={
            "effect:write": {"finding": "The new state is correct", "evidence": ["a2"]}})["accepted"])
        self.assertTrue(self.state.finish()["accepted"])

    def test_explicit_reopen_permits_new_evidence(self):
        self.state.role = "verify"
        self.observe("a")
        self.checkpoint(completed={"A": ["a"]})
        self.assertTrue(self.checkpoint(reopen=["A"])["accepted"])
        self.assertFalse(self.state.complete())
        self.observe("a2")
        self.assertTrue(self.checkpoint(completed={"A": ["a2"]})["accepted"])

    def test_external_revision_invalidates_stale_completion(self):
        self.state.role = "verify"
        self.observe("a")
        self.checkpoint(completed={"A": ["a"]})
        self.state.refresh({self.resource: "2"})
        self.assertFalse(self.state.complete())
        self.assertFalse(self.checkpoint(completed={"A": ["a"]})["accepted"])

    def test_checkpoint_rejection_is_fully_atomic(self):
        before = copy.deepcopy(asdict(self.state))
        result = self.checkpoint(criteria=["A", "B"], verification={
            "B": {"method": "Observe B", "resources": []}}, completed={"B": ["missing"]},
            decisions=["new decision"], strategy="new strategy", kind="mutation", resources=[self.resource])
        self.assertFalse(result["accepted"])
        self.assertEqual(asdict(self.state), before)

    def test_invalid_resolution_rolls_back_other_checkpoint_updates(self):
        self.state.role = "verify"
        self.observe("a")
        before = copy.deepcopy(asdict(self.state))
        self.assertFalse(self.checkpoint(completed={"A": ["a"]}, resolutions={
            "missing": {"finding": "resolved", "evidence": ["a"]}})["accepted"])
        self.assertEqual(asdict(self.state), before)

    def test_incident_resolution_does_not_require_criterion_completion(self):
        self.observe("partial", Outcome.UNCERTAIN, effectful=True, uncertain=True)
        self.state.role = "verify"
        self.observe("check")
        self.assertTrue(self.checkpoint(resolutions={"effect:partial": {
            "finding": "No partial mutation remains", "evidence": ["check"]}})["accepted"])
        self.assertFalse(self.state.obligations)
        self.assertFalse(self.state.complete())

    def test_decision_and_strategy_text_do_not_verify_progress(self):
        self.assertTrue(self.checkpoint(decisions=["Try another approach"], strategy="new approach")["accepted"])
        self.assertFalse(self.state.complete())
        self.assertFalse(self.state.evidence)
        self.assertEqual(self.state.status, Lifecycle.ACTIVE)

    def test_generic_failure_and_repetition_do_not_support_blocking(self):
        self.observe("failed", Outcome.FAILED)
        self.assertFalse(self.state.defer("blocked", "A", "service", ["failed"], "Restore service")["accepted"])
        self.assertFalse(self.state.defer("blocked", "A", "", ["failed"], "")["accepted"])
        self.assertEqual(self.state.status, Lifecycle.ACTIVE)

    def test_supported_external_dependency_can_block_and_resume_same_ledger(self):
        self.observe("unavailable", Outcome.EXTERNAL_BLOCKER, dependency="service")
        identity = self.state.id
        self.assertTrue(self.state.defer("blocked", "A", "service", ["unavailable"], "Restore service")["accepted"])
        self.state.resume()
        self.assertEqual(self.state.id, identity)
        self.assertIn("unavailable", self.state.evidence)
        self.assertFalse(self.state.finish()["accepted"])
        self.state.role = "verify"
        self.observe("available")
        self.assertTrue(self.state.resolve_dependency(["available"], "Service is available")["accepted"])
        self.assertFalse(self.state.dependencies)

    def test_permission_input_is_waiting_not_failed_or_blocked(self):
        result = normalize_result({"status": "needs_input"})
        self.assertEqual(result.outcome, Outcome.WAITING)
        self.state.observe("request", {}, result, "input", {})
        self.assertTrue(self.state.defer("waiting", "A", "user_input", ["input"], "Select the target")["accepted"])
        self.assertEqual(self.state.status, Lifecycle.WAITING)

    def test_interruption_and_resource_limits_have_explicit_semantics(self):
        self.observe("a")
        identity = self.state.id
        for status in (Lifecycle.INTERRUPTED, Lifecycle.LIMIT_REACHED):
            self.state.suspend(status, "Explicit interruption or configured limit")
            self.assertEqual(self.state.status, status)
            self.state.resume()
            self.assertEqual(self.state.id, identity)
            self.assertIn("a", self.state.evidence)

    def test_localized_status_prose_is_not_successful_evidence(self):
        for text in ("Error al editar", "The task succeeded", "denied", "No matches"):
            self.assertEqual(normalize_result(text).outcome, Outcome.UNCERTAIN)

    def test_error_looking_source_content_remains_successful_when_typed(self):
        self.assertEqual(normalize_result(ActionResult(Outcome.SUCCESS, "Error: source text")).outcome,
                         Outcome.SUCCESS)


if __name__ == "__main__":
    unittest.main()
