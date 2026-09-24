import asyncio
import tempfile
import unittest
from pathlib import Path

from src.init.agent.models import (ExecutionPlan, ExecutionState, PlanStep,
                                   VerificationResult)
from src.init.agent.orchestrator import AgentOrchestrator
from src.init.agent.persistence import AgentStore


class RejectedPlanLoggingTest(unittest.TestCase):
    def test_rejected_write_plan_is_logged_and_feedback_replans_read_only(self):
        class Backend:
            def __init__(self):
                self.feedback = []

            async def plan(self, task, max_steps, project_context=None,
                           validation_feedback=None):
                self.feedback.append(validation_feedback)
                write = validation_feedback is None
                return ExecutionPlan(
                    request_id="a" * 32,
                    goal="Inspect the project",
                    steps=[PlanStep(
                        id="step", title="Inspect", instruction="Inspect the project",
                        tool_name="create_file" if write else "read_file",
                        tool_args={"path": "report.txt", "content": "x"}
                        if write else {"path": "README.md"},
                        requires_approval=write,
                    )],
                )

            async def validate_plan(self, task, plan):
                if plan.steps[0].tool_name == "create_file":
                    return VerificationResult(
                        success=False, summary="Unrequested file write")
                return VerificationResult(success=True, summary="valid")

            async def verify(self, task, plan, observations):
                return VerificationResult(success=True, summary="verified")

            async def finalize(self, task, observations, verification):
                return "done"

        with tempfile.TemporaryDirectory() as directory:
            backend = Backend()
            store = AgentStore(Path(directory) / "runs.sqlite3")
            events = []
            result = asyncio.run(AgentOrchestrator(
                backend, {"read_file": lambda path: "read"}, store,
                max_retries=0).run("Inspect the project", on_event=events.append))

        self.assertEqual(result.state, ExecutionState.COMPLETED)
        self.assertEqual(backend.feedback, [None, "Unrequested file write"])
        rejected = next(event for event in events
                        if event.type.value == "plan_validated"
                        and not event.payload["success"])
        self.assertEqual(rejected.payload["summary"], "Unrequested file write")
        self.assertEqual(rejected.payload["proposed_plan"]["steps"], [{
            "id": "step", "tool_name": "create_file",
            "tool_args": {"path": "report.txt", "content": "x"},
            "requires_approval": True,
        }])


if __name__ == "__main__":
    unittest.main()
