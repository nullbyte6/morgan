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

import inspect
import json
from collections.abc import Iterable

from pydantic_ai import Agent

from .models import ExecutionPlan, VerificationResult


class PydanticAgentBackend:
    def __init__(self, model, tools: Iterable, *, base_instructions=()):
        tool_descriptions = []
        for function in tools:
            signature = inspect.signature(function)
            documentation = (inspect.getdoc(function) or "").splitlines()
            description = documentation[0] if documentation else "No description"
            tool_descriptions.append(
                f"- {function.__name__}{signature}: {description[:180]}"
            )
        catalog = "\n".join(tool_descriptions)
        base = list(base_instructions)
        self.planner = Agent(
            model=model,
            output_type=ExecutionPlan,
            instructions=[*base, (
                "Create a bounded execution plan for a local autonomous agent. "
                "Each step must either call exactly one available tool or perform "
                "a reasoning-only operation. Use the exact Python parameter names "
                "and JSON-compatible argument values. Mark operations that delete, "
                "overwrite, send, publish, install, uninstall, terminate, or make "
                "system changes as requiring approval. Do not invent tools. Keep "
                "the plan minimal and order dependent work correctly.\n\n"
                f"Available tools:\n{catalog}"
            )],
        )
        self.reasoner = Agent(
            model=model,
            instructions=[*base, (
                "You are the reasoning component of a local autonomous agent. "
                "Use only the supplied observations. Do not claim to call tools "
                "or perform external actions. Return concise plain text."
            )],
        )
        self.verifier = Agent(
            model=model,
            output_type=VerificationResult,
            instructions=[*base, (
                "Verify whether the execution observations satisfy the requested "
                "task. Be strict about tool failures and missing required results."
            )],
        )
        self.writer = Agent(
            model=model,
            instructions=[*base, (
                "Produce the final response for the user from a completed autonomous "
                "run. Report confirmed results and any relevant limitations concisely."
            )],
        )

    async def plan(self, task: str, max_steps: int) -> ExecutionPlan:
        result = await self.planner.run(
            f"Task: {task}\nMaximum steps: {max_steps}"
        )
        return result.output

    async def execute(self, instruction: str, observations: list[str]) -> str:
        result = await self.reasoner.run(
            f"Instruction: {instruction}\nObservations:\n"
            + "\n".join(observations)
        )
        return result.output

    async def verify(self, task: str, plan: ExecutionPlan,
                     observations: list[str]) -> VerificationResult:
        result = await self.verifier.run(
            json.dumps({
                "task": task,
                "plan": plan.model_dump(mode="json"),
                "observations": observations,
            }, ensure_ascii=False)
        )
        return result.output

    async def finalize(self, task: str, observations: list[str],
                       verification: VerificationResult) -> str:
        result = await self.writer.run(
            json.dumps({
                "task": task,
                "observations": observations,
                "verification": verification.model_dump(mode="json"),
            }, ensure_ascii=False)
        )
        return result.output
