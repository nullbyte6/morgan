"""Execution, context and source-tool integration regressions without external services."""

import asyncio
import hashlib
import json
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel

from src.init.task_control import TaskControl
from src.init.task_effects import content_revision, file_resource, resources_for
from src.init.task_outcomes import ActionResult, Outcome
from src.init.task_state import Lifecycle


class Context:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.counter = 0

    def _store(self, raw, extension, label):
        self.counter += 1
        path = self.directory / f"artifact-{self.counter}{extension}"
        path.write_text(raw, encoding="utf-8")
        return f"[{label}]({path.as_posix()})"


class ExecutionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.context = Context(self.temporary.name)
        self.controller = TaskControl("Deliver the objective", self.context, threading.Event())
        self.path = Path(self.temporary.name, "source.py")
        self.path.write_text("value = 1\n", encoding="utf-8")
        self.resource = file_resource(self.path)

    def contract(self, kind="mutation"):
        return self.controller.task_checkpoint("inspect", ["A"], {
            "A": {"method": "Inspect and validate current source", "resources": [self.resource]}}, kind=kind)

    async def test_all_effectful_actions_are_gated_without_contract(self):
        async def forbidden(arguments):
            self.fail("An unauthorized effect reached its handler")
        for index, name in enumerate(("edit_code", "create_code", "create_file", "execute_command", "git_push",
                                     "send_email", "update_config", "install_app", "run_quick_command")):
            result = await self.controller.execute(name, {}, str(index), forbidden)
            self.assertEqual(result["code"], "mutation_contract_required")
        self.assertFalse(self.controller.accept_output())

    async def test_partial_exception_and_timeout_require_reconciliation(self):
        self.contract()
        for index, error in enumerate((OSError("write failed"), TimeoutError("timed out"))):
            async def handler(arguments):
                self.path.write_text(f"value = {index + 2}\n", encoding="utf-8")
                raise error
            result = await self.controller.execute("edit_code", {"path": str(self.path)}, f"partial{index}", handler)
            self.assertEqual(result["outcome"], Outcome.FAILED)
            self.assertEqual(self.controller.state.obligations[f"effect:partial{index}"].kind, "reconcile")
            self.assertFalse(self.controller.accept_output())

    async def test_typed_precondition_rejection_does_not_create_effect(self):
        self.contract()
        async def handler(arguments):
            return ActionResult(Outcome.REJECTED, "No exact match", "exact_match_required")
        await self.controller.execute("edit_code", {"path": str(self.path)}, "rejected", handler)
        self.assertFalse(self.controller.state.obligations)
        self.assertEqual(self.controller.state.status, Lifecycle.ACTIVE)

    async def test_explicit_user_input_request_waits_and_resumes_same_task(self):
        self.contract("read_only")
        identity = self.controller.state.id
        self.assertTrue(self.controller.task_request_input("A", "Which target should I inspect?")["accepted"])
        self.assertEqual(self.controller.state.status, Lifecycle.WAITING)
        self.assertFalse(self.controller.accept_output())
        self.controller.resume(self.context, threading.Event(), "Inspect the current source")
        refs = [key for key, item in self.controller.state.evidence.items() if item.tool == "user_input"]
        self.assertTrue(self.controller.task_resolve_dependency(refs, "Target supplied")["accepted"])
        self.assertEqual(self.controller.state.id, identity)
        self.assertEqual(self.controller.state.status, Lifecycle.ACTIVE)

    async def test_web_presentation_effect_does_not_block_read_only_verification(self):
        self.controller.task_checkpoint("verify", ["Research"], {
            "Research": {"method": "Inspect returned web evidence", "resources": ["domain:web"]}}, kind="read_only")
        async def search(arguments):
            return ActionResult(Outcome.SUCCESS, {"results": ["Observed fact"]})
        await self.controller.execute("search_web", {"query": "fact"}, "search", search)
        self.assertFalse(self.controller.state.obligations)
        self.assertEqual(self.controller.state.evidence["search"].effects, ["domain:presentation"])
        self.assertTrue(self.controller.task_checkpoint("verify", [], completed={"Research": ["search"]})["accepted"])
        self.assertTrue(self.controller.task_finish()["accepted"])

    async def test_verification_command_can_verify_stable_source_but_not_its_own_effects(self):
        self.contract()
        self.controller.task_checkpoint("verify", [], resources=[self.resource])
        async def command(arguments):
            return ActionResult(Outcome.SUCCESS, {"exit_code": 0})
        await self.controller.execute("execute_command", {"command": "check"}, "check", command)
        state = self.controller.state
        self.assertTrue(state.valid_evidence(["check"], [self.resource]))
        self.assertFalse(state.valid_evidence(["check"], ["domain:system"]))
        self.assertFalse(self.controller.task_finish()["accepted"])
        async def inspect(arguments):
            return ActionResult(Outcome.SUCCESS, {"healthy": True})
        await self.controller.execute("check_system_health", {}, "inspect", inspect)
        result = self.controller.task_checkpoint("verify", [], completed={"A": ["check"]}, resolutions={
            "effect:check": {"finding": "Command terminated and current system state observed", "evidence": ["inspect"]}})
        self.assertTrue(result["accepted"])
        self.assertTrue(self.controller.task_finish()["accepted"])

    async def test_verification_command_that_changes_source_cannot_verify_that_source(self):
        self.contract()
        self.controller.task_checkpoint("verify", [], resources=[self.resource])
        async def command(arguments):
            self.path.write_text("value = 2\n", encoding="utf-8")
            return ActionResult(Outcome.SUCCESS, {"exit_code": 0})
        await self.controller.execute("execute_command", {"command": "change"}, "change", command)
        self.assertFalse(self.controller.state.valid_evidence(["change"], [self.resource]))

    async def test_file_changes_invalidate_verified_contract_at_output_boundary(self):
        self.contract("read_only")
        self.controller.task_checkpoint("verify", [], resources=[self.resource])
        async def read(arguments):
            return ActionResult(Outcome.SUCCESS, self.path.read_text(encoding="utf-8"))
        await self.controller.execute("read_code", {"path": str(self.path)}, "read", read)
        self.controller.task_checkpoint("verify", [], completed={"A": ["read"]})
        self.assertTrue(self.controller.task_finish()["accepted"])
        self.path.write_text("value = 2\n", encoding="utf-8")
        self.assertFalse(self.controller.accept_output())
        self.assertEqual(self.controller.state.status, Lifecycle.ACTIVE)
        self.assertEqual(self.controller.state.criteria["A"].evidence, [])

    async def test_repeated_reads_reexecute_and_can_reacquire_compacted_evidence(self):
        self.contract("read_only")
        count = 0
        async def handler(arguments):
            nonlocal count
            count += 1
            return ActionResult(Outcome.SUCCESS, "unchanged source")
        for index in range(10):
            result = await self.controller.execute("read_code", {"path": str(self.path)}, str(index), handler)
            self.assertEqual(result["data"], "unchanged source")
        self.assertEqual(count, 10)
        self.assertEqual(self.controller.task_read_evidence("0")["result"]["data"], "unchanged source")
        self.assertEqual(self.controller.state.status, Lifecycle.ACTIVE)

    async def test_native_and_text_calls_share_execution_and_validation(self):
        def read_code(path: str) -> dict:
            return ActionResult(Outcome.SUCCESS, Path(path).read_text(encoding="utf-8")).payload()
        other = TaskControl("Deliver the objective", self.context, threading.Event())
        for controller in (self.controller, other):
            controller.task_checkpoint("verify", ["A"], {
                "A": {"method": "Read current source", "resources": [self.resource]}}, kind="read_only")
        responses = iter([
            ModelResponse(parts=[ToolCallPart("read_code", {"path": str(self.path)}, "read")]),
            ModelResponse(parts=[TextPart("Observed")]),
        ])
        def model(messages, info):
            return next(responses)
        agent = Agent(FunctionModel(model), tools=[read_code])
        await agent.run("Read", capabilities=[self.controller])
        with patch.dict(sys.modules, {"src.init.tools": SimpleNamespace(TOOLS=[read_code])}):
            await other.invoke("read_code", {"path": str(self.path)}, "read")
        native = self.controller.state.evidence["read"]
        text = other.state.evidence["read"]
        for attribute in ("outcome", "role", "revisions", "effectful", "digest", "result"):
            self.assertEqual(getattr(native, attribute), getattr(text, attribute))
        self.assertFalse(self.controller.accept_output())
        self.assertFalse(other.accept_output())

    async def test_validation_rejection_is_shared_and_atomic(self):
        before = self.controller.state.snapshot()
        result = await self.controller.invoke("task_checkpoint", {"phase": "wrong", "criteria": ["A"]}, "invalid")
        self.assertEqual(result["outcome"], Outcome.REJECTED)
        self.assertEqual(self.controller.state.snapshot(), before)

    async def test_compaction_preserves_contract_and_evidence_retrieval(self):
        self.contract("read_only")
        self.controller.state.role = "verify"
        self.controller.state.observe("read_code", {}, ActionResult(Outcome.SUCCESS, "source" * 2000), "old",
                                      {self.resource: content_revision(self.resource)})
        self.controller.context_characters = 2000
        messages = [ModelRequest(parts=[UserPromptPart("Original objective")]),
                    ModelResponse(parts=[ToolCallPart("read_code", {}, "old")]),
                    ModelRequest(parts=[ToolReturnPart("read_code", "source" * 2000, "old")]),
                    ModelResponse(parts=[TextPart("Continue")])]
        request = SimpleNamespace(messages=messages)
        await self.controller.before_model_request(SimpleNamespace(messages=messages), request)
        snapshot = json.loads(request.messages[-1].parts[0].content.split(": ", 1)[1])
        self.assertEqual(snapshot["objective"], self.controller.state.objective)
        self.assertIn("A", snapshot["criteria"])
        self.assertIn("obligations", snapshot)
        self.assertIn("dependencies", snapshot)
        self.assertIn(self.resource, snapshot["revisions"])
        self.assertEqual(self.controller.task_read_evidence("old")["result"]["data"], "source" * 2000)
        pending = set()
        for message in request.messages:
            for part in message.parts:
                if part.part_kind == "tool-call":
                    pending.add(part.tool_call_id)
                if part.part_kind == "tool-return":
                    self.assertIn(part.tool_call_id, pending)
                    pending.remove(part.tool_call_id)
        self.assertFalse(pending)

    async def test_resume_retains_identity_and_waiting_input_provenance(self):
        self.contract("read_only")
        self.controller.state.observe("request", {}, ActionResult(Outcome.WAITING, "Choose", dependency="user_input"),
                                      "request", {})
        self.controller.task_defer("waiting", "A", "user_input", ["request"], "Select the target")
        identity = self.controller.state.id
        self.controller.resume(self.context, threading.Event(), prompt="Use the second target")
        self.assertEqual(self.controller.state.id, identity)
        ref = next(key for key in self.controller.state.evidence if key.startswith("input_"))
        self.assertTrue(self.controller.task_resolve_dependency([ref], "The user selected the target")["accepted"])
        self.assertEqual(self.controller.state.status, Lifecycle.ACTIVE)
        self.assertFalse(self.controller.accept_output())

    async def test_cancelled_effect_records_uncertainty_without_replay(self):
        self.contract()
        async def handler(arguments):
            self.path.write_text("value = 2\n", encoding="utf-8")
            raise asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.controller.execute("edit_code", {"path": str(self.path)}, "cancelled", handler)
        self.assertEqual(self.controller.state.status, Lifecycle.INTERRUPTED)
        self.assertIn("effect:cancelled", self.controller.state.obligations)

    async def test_original_trace_cannot_falsely_block_or_complete(self):
        fixture = json.loads(Path(__file__).with_name("task_control_trace.json").read_text(encoding="utf-8"))
        self.controller.state.objective = fixture["objective"]
        with patch("src.init.task_control.content_revision", return_value="unchanged"):
            for attempt in fixture["attempts"]:
                async def handler(arguments):
                    return ActionResult(Outcome(attempt["outcome"]), attempt["data"])
                await self.controller.execute(attempt["tool"], attempt["arguments"], attempt["call_id"], handler)
                self.assertEqual(self.controller.state.status, Lifecycle.ACTIVE)
            self.assertEqual(len(fixture["attempts"]), 44)
            self.assertFalse(self.controller.accept_output())
            self.assertFalse(self.controller.task_finish()["accepted"])
            self.assertFalse(self.controller.task_finish(direct=True)["accepted"])

    async def test_observation_changed_during_read_is_not_verification(self):
        self.contract("read_only")
        self.controller.state.role = "verify"
        async def handler(arguments):
            original = self.path.read_text(encoding="utf-8")
            self.path.write_text("value = 2\n", encoding="utf-8")
            return ActionResult(Outcome.SUCCESS, original)
        result = await self.controller.execute("read_code", {"path": str(self.path)}, "racing", handler)
        self.assertEqual(result["outcome"], Outcome.UNCERTAIN)
        self.assertFalse(self.controller.task_checkpoint("verify", [], completed={"A": ["racing"]})["accepted"])


class SourceAndGitTests(unittest.TestCase):
    def test_quick_group_scopes_include_nested_effects(self):
        quick = types.ModuleType("src.init.quick_commands")
        quick.TOOL_ALIASES = {}
        quick.load_quick_commands = lambda: {"group": {"actions": [
            {"tool": "create_file", "arguments": {"path": "new.txt"}},
            {"tool": "send_email", "arguments": {}}]}}
        with patch.dict(sys.modules, {"src.init.quick_commands": quick}):
            spec, resources = resources_for("run_quick_command", {"name": "group"})
        self.assertTrue(spec.effectful)
        self.assertIn(file_resource("new.txt"), resources)
        self.assertIn("domain:email", resources)

    def test_git_directory_and_index_revisions_track_actual_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*arguments):
                return subprocess.run(["git", "-C", directory, *arguments], capture_output=True, check=True)
            git("init", "-q")
            folder = root / "nested"
            folder.mkdir()
            path = folder / "source.py"
            path.write_text("value = 1\n", encoding="utf-8")
            first = content_revision(file_resource(folder))
            path.write_text("value = 2\n", encoding="utf-8")
            self.assertNotEqual(content_revision(file_resource(folder)), first)
            resource = "domain:git:" + str(root)
            first_index = content_revision(resource)
            self.assertIsNotNone(first_index)
            git("add", ".")
            self.assertNotEqual(content_revision(resource), first_index)

    def test_git_status_is_unchanged_while_dirty_and_untracked_revisions_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*arguments):
                return subprocess.run(["git", "-C", directory, *arguments], capture_output=True,
                                      text=True, check=True).stdout
            git("init", "-q")
            path = root / "tracked.py"
            path.write_text("value = 1\n", encoding="utf-8")
            git("add", "tracked.py")
            git("-c", "user.name=Regression", "-c", "user.email=regression@example.invalid",
                "commit", "-qm", "Add baseline")
            path.write_text("value = 2\n", encoding="utf-8")
            first_status = git("status", "--porcelain")
            first = content_revision(file_resource(path))
            path.write_text("value = 3\n", encoding="utf-8")
            self.assertEqual(git("status", "--porcelain"), first_status)
            self.assertNotEqual(content_revision(file_resource(path)), first)
            untracked = root / "untracked.py"
            untracked.write_text("value = 1\n", encoding="utf-8")
            first_status = git("status", "--porcelain")
            first = content_revision(file_resource(untracked))
            untracked.write_text("value = 2\n", encoding="utf-8")
            self.assertEqual(git("status", "--porcelain"), first_status)
            self.assertNotEqual(content_revision(file_resource(untracked)), first)

    def test_new_source_creation_is_exclusive_validated_and_confined(self):
        from src.init import self_code
        fake_brain = types.ModuleType("src.init.brain")
        fake_brain.decode_text = lambda raw: (raw.decode("utf-8"), "utf-8")
        with tempfile.TemporaryDirectory() as directory, patch.object(self_code, "ARLO_ROOT", Path(directory)), patch.dict(
                sys.modules, {"src.init.brain": fake_brain}):
            self.assertEqual(self_code.create_code("new.py", "value = 1\n")["outcome"], Outcome.SUCCESS)
            self.assertEqual(self_code.verify_code("new.py")["outcome"], Outcome.SUCCESS)
            self.assertEqual(self_code.create_code("new.py", "value = 2\n")["outcome"], Outcome.REJECTED)
            self.assertEqual(Path(directory, "new.py").read_text(encoding="utf-8"), "value = 1\n")
            self.assertEqual(self_code.create_code("invalid.py", "def invalid(:\n")["outcome"], Outcome.REJECTED)
            self.assertFalse(Path(directory, "invalid.py").exists())
            for path in ("../outside.py", ".git/source.py", ".venv/source.py"):
                self.assertEqual(self_code.create_code(path, "value = 1\n")["outcome"], Outcome.REJECTED)
            self.assertEqual(sorted(path.name for path in Path(directory).iterdir()), ["new.py"])


if __name__ == "__main__":
    unittest.main()
