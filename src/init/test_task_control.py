"""Regression contracts for supervised mutation verification, without model or UI services."""

import asyncio
import tempfile
import threading
import unittest
from pathlib import Path

from src.init import brain
from src.init.session_log import SessionContext
from src.init.task_control import ExecutionControl
from src.init.task_outcomes import Outcome
from src.init.task_state import Lifecycle


class PromotedMutationVerificationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        context = SessionContext("session", root / "log")
        context.directory.mkdir(parents=True)
        self.path = str(root / "work" / "agent_verification.md")
        self.content = "# Agent verification\n\nCreated to verify the supervised flow."
        self.control = ExecutionControl("Create the file, then reread and verify it.", context, threading.Event())
        self.creations = 0

    async def create(self, values):
        self.creations += 1
        return brain.create_file(**values)

    async def read(self, values):
        return brain.read_file(**values)

    def run_tool(self, name, call_id, **arguments):
        handler = self.create if name == "create_file" else self.read
        return asyncio.run(self.control.execute(name, arguments, call_id, handler))

    def checkpoint(self, **values):
        return self.control.call_control("task_checkpoint", values)

    def contract(self, phase):
        return self.checkpoint(phase=phase, kind="read_only", criteria=["User outcome"],
                               verification={"User outcome": {"method": "Observable check", "resources": []}})

    def resolve(self, evidence):
        return self.checkpoint(phase="verify", criteria=[], completed={"User outcome": [evidence]},
                               resolutions={"effect:create": {"finding": "The file holds one requested section.",
                                                              "evidence": [evidence]}})

    def create_and_promote(self):
        self.assertFalse(Path(self.path).exists())
        self.assertEqual(self.run_tool("create_file", "create", path=self.path, content=self.content)["outcome"],
                         Outcome.SUCCESS)
        rejected = self.run_tool("read_file", "promotion", path=self.path)
        self.assertEqual(rejected["code"], "contract_required")
        return self.control.state.requirements()

    def assert_completed(self, reread):
        self.assertEqual(reread["data"]["content"].count("# Agent verification"), 1)
        self.assertTrue(self.resolve(reread["evidence_id"])["accepted"])
        self.assertTrue(self.control.call_control("task_finish", {"output": "Verified."})["accepted"])
        self.assertEqual(self.control.state.status, Lifecycle.COMPLETE)
        self.assertEqual(self.creations, 1)
        self.assertEqual([item.tool for item in self.control.state.evidence.values() if item.effectful], ["create_file"])

    def test_promoted_creation_follows_contract_template_to_verified_completion(self):
        requirements = self.create_and_promote()
        template = next(item for item in requirements if item["code"] == "contract_required")
        self.assertIn("effect:create", self.control.state.obligations)
        self.assertTrue(self.contract(template["fields"]["phase"])["accepted"])
        reread = self.run_tool("read_file", "reread", path=self.path)
        self.assertEqual(self.control.state.evidence[reread["evidence_id"]].role, "verify")
        self.assert_completed(reread)

    def test_inspection_reread_recovers_through_fresh_verification(self):
        self.create_and_promote()
        self.assertTrue(self.contract("inspect")["accepted"])
        inspection = self.run_tool("read_file", "inspection", path=self.path)
        rejected = self.resolve(inspection["evidence_id"])
        self.assertFalse(rejected["accepted"])
        self.assertIn("verify", rejected["reason"])
        self.assertTrue(self.checkpoint(phase="verify", criteria=[])["accepted"])
        reread = self.run_tool("read_file", "reread", path=self.path)
        self.assertNotEqual(reread["evidence_id"], inspection["evidence_id"])
        self.assert_completed(reread)


if __name__ == "__main__":
    unittest.main()
