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
import uuid
from collections.abc import Iterable

from pydantic_ai import Agent, ModelRetry, NativeOutput

from .models import ExecutionPlan, VerificationResult


class PydanticAgentBackend:
    def __init__(self, model, tools: Iterable, *, base_instructions=()):
        tools = list(tools)
        tool_names = {function.__name__ for function in tools}
        tool_signatures = {function.__name__: inspect.signature(function)
                           for function in tools}
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
        self.model = model
        self.tool_names = tool_names
        self.tool_signatures = tool_signatures
        self.planner_instructions = [*base, (
            "Create a bounded execution plan for a local autonomous agent. "
            "Every plan step must call exactly one available tool. Final "
            "reasoning and synthesis happen after the plan executes. "
            "Derive the plan only from ORIGINAL_REQUEST in the current prompt. "
            "Never reuse examples, filenames, goals, or actions from another task. "
            "Use the exact Python parameter names "
            "and JSON-compatible argument values. Mark operations that delete, "
            "overwrite, send, publish, install, uninstall, terminate, or make "
            "system changes as requiring approval. Never create or modify a file "
            "unless the current request explicitly requires it. Do not invent tools. "
            "Keep the plan minimal and order dependent work correctly.\n\n"
            f"Available tools:\n{catalog}\n\n"
            "Tool selection rules:\n"
            "- For Git state or status, use git_status.\n"
            "- Use list_code only to list source entries.\n"
            "- Use read_code only for a specific source file, never a directory.\n"
            "- Repository inspection must use list_code/read_code or list_files/read_file.\n"
            "- Python syntax checks must execute a read-only check and must not create unrelated files.\n"
            "- A request to display the result in a response workspace is handled by the host; "
            "plan only the work needed to produce the result."
        )]
        self.plan_validator = Agent(
            model=model,
            output_type=NativeOutput(
                VerificationResult,
                name="plan_assessment",
                description="Whether a proposed plan directly addresses its original request.",
                strict=True,
            ),
            retries={"tools": 1, "output": 2},
            instructions=[*base, (
                "Compare ORIGINAL_REQUEST with PROPOSED_PLAN before execution. "
                "Return success=false if the goal, filenames, tool choices, or actions "
                "are unrelated, invented, insufficient to produce evidence, or include "
                "side effects not explicitly required. A syntax-check request must run "
                "an actual syntax check. Repository claims must be backed by file or "
                "repository inspection tools. Return a concrete diagnostic summary."
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
            output_type=NativeOutput(
                VerificationResult,
                name="verification_result",
                description="Whether the observations satisfy the task.",
                strict=True,
            ),
            retries={"tools": 1, "output": 2},
            instructions=[*base, (
                "Verify whether the execution observations satisfy the requested "
                "task. Be strict about tool failures and missing required results."
            )],
        )
        self.writer = Agent(
            model=model,
            instructions=[*base, (
                "Produce the final response for the user from a completed autonomous "
                "run. Report confirmed results and any relevant limitations concisely. "
                "Never say that a file was inspected, a command or test was run, or an "
                "external action occurred unless a successful tool observation explicitly "
                "records it. Do not add filenames, components, or results absent from the "
                "observations."
            )],
        )

    async def plan(self, task: str, max_steps: int) -> ExecutionPlan:
        request_id = uuid.uuid4().hex
        planner = Agent(
            model=self.model,
            output_type=NativeOutput(
                ExecutionPlan,
                name="execution_plan",
                description="A bounded ordered plan using available tools.",
                strict=True,
            ),
            retries={"tools": 1, "output": 2},
            instructions=self.planner_instructions,
        )

        @planner.output_validator
        def validate_execution_plan(plan: ExecutionPlan) -> ExecutionPlan:
            if plan.request_id != request_id:
                raise ModelRetry("Copy REQUEST_ID exactly from the current prompt.")
            step_ids = [step.id for step in plan.steps]
            if len(step_ids) != len(set(step_ids)):
                raise ModelRetry("Every plan step must have a unique id.")
            unknown = sorted({step.tool_name for step in plan.steps
                              if step.tool_name not in self.tool_names})
            if unknown:
                raise ModelRetry(
                    "Use only available tool names. Unknown: "
                    + ", ".join(unknown))
            invalid_arguments = []
            for step in plan.steps:
                try:
                    self.tool_signatures[step.tool_name].bind(**step.tool_args)
                except TypeError as error:
                    invalid_arguments.append(f"{step.id}: {error}")
            if invalid_arguments:
                raise ModelRetry(
                    "Correct the tool arguments using the listed signatures. "
                    + " | ".join(invalid_arguments))
            return plan

        result = await planner.run(
            f"REQUEST_ID: {request_id}\nORIGINAL_REQUEST:\n{task}\n"
            f"MAXIMUM_STEPS: {max_steps}"
        )
        return result.output

    async def validate_plan(self, task: str,
                            plan: ExecutionPlan) -> VerificationResult:
        result = await self.plan_validator.run(
            json.dumps({
                "ORIGINAL_REQUEST": task,
                "PROPOSED_PLAN": plan.model_dump(mode="json"),
            }, ensure_ascii=False)
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
