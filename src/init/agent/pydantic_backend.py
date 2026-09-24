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
import logging
import re
import subprocess
import traceback
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any, get_type_hints

from pydantic_ai import Agent, ModelRetry, NativeOutput
from pydantic_ai.messages import RetryPromptPart
from pydantic_ai.models.wrapper import WrapperModel
from pydantic import ConfigDict, ValidationError, create_model

from .models import (ExecutionPlan, ExecutionPlanDraft, PlanStep,
                     VerificationResult)


PYTHON_SYNTAX_COMMAND = (
    "python -c \"import pathlib,subprocess; "
    "files=subprocess.check_output(['git','ls-files','*.py'], "
    "text=True).splitlines(); "
    "[compile(pathlib.Path(p).read_text(encoding='utf-8-sig'), p, 'exec') "
    "for p in files]\""
)


LOGGER = logging.getLogger("arlo.agent.planning")
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class PlanningOutputError(RuntimeError):
    pass


def _redact_output(content: str, tool_names: set[str]) -> str:
    try:
        value = json.loads(content)
    except (TypeError, ValueError, json.JSONDecodeError):
        keys = re.findall(r'"([A-Za-z0-9_]+)"\s*:', content)
        selected_tools = sorted(name for name in tool_names if name in content)
        return json.dumps({
            "invalid_json": True,
            "characters": len(content),
            "keys": keys[:100],
            "recognized_tools": selected_tools,
        }, ensure_ascii=False)

    def redact(value, key=None):
        if isinstance(value, dict):
            return {name: redact(item, name) for name, item in value.items()}
        if isinstance(value, list):
            return [redact(item, key) for item in value]
        if key == "tool_name" and value in tool_names:
            return value
        if isinstance(value, str):
            return "<redacted>"
        return value

    return json.dumps(redact(value), ensure_ascii=False)


def _redact_feedback(part: RetryPromptPart) -> str:
    if isinstance(part.content, list):
        errors = [{
            "type": error.get("type"),
            "loc": error.get("loc"),
            "msg": error.get("msg"),
        } for error in part.content]
        return json.dumps(errors, ensure_ascii=False, default=str)
    feedback = str(part.content)
    feedback = re.sub(r"[A-Za-z]:\\[^\s]+", "<redacted-path>", feedback)
    feedback = re.sub(r"[\w.+-]+@[\w.-]+", "<redacted-email>", feedback)
    return feedback[:2000]


def _safe_exception_chain(error: Exception) -> list[dict[str, Any]]:
    chain = []
    current = error
    while current is not None:
        if isinstance(current, ValidationError):
            detail = current.errors(
                include_url=False, include_context=False, include_input=False)
        else:
            message = re.sub(
                r"input_value=.*?(?=, input_type=|\]$|$)",
                "input_value=<redacted>", str(current), flags=re.DOTALL)
            detail = message[:2000]
        chain.append({"type": type(current).__name__, "detail": detail})
        current = current.__cause__
    return chain


class _PlanningTraceModel(WrapperModel):
    def __init__(self, wrapped, tool_names: set[str]):
        super().__init__(wrapped)
        self.tool_names = tool_names
        self.attempts = 0
        self.records = []

    async def request(self, messages, model_settings, model_request_parameters):
        self.attempts += 1
        feedback = [
            _redact_feedback(part)
            for message in messages
            for part in message.parts
            if isinstance(part, RetryPromptPart)
        ]
        if feedback:
            LOGGER.warning(
                "Planning retry %d feedback: %s",
                self.attempts, feedback[-1][:2000])
        response = await self.wrapped.request(
            messages, model_settings, model_request_parameters)
        contents = [
            part.content for part in response.parts
            if isinstance(getattr(part, "content", None), str)
        ]
        for content in contents:
            redacted = _redact_output(content, self.tool_names)
            self.records.append({
                "attempt": self.attempts,
                "finish_reason": response.finish_reason,
                "characters": len(content),
                "output": redacted,
            })
            LOGGER.debug(
                "Planning model output attempt=%d finish_reason=%s "
                "characters=%d output=%s",
                self.attempts, response.finish_reason, len(content),
                redacted)
        if response.finish_reason == "length":
            LOGGER.warning(
                "Planning model output truncated attempt=%d characters=%d",
                self.attempts, sum(len(content) for content in contents))
        return response


class PydanticAgentBackend:
    def __init__(self, model, tools: Iterable, *, base_instructions=()):
        tools = list(tools)
        tool_names = {function.__name__ for function in tools}
        tool_signatures = {function.__name__: inspect.signature(function)
                           for function in tools}
        tool_descriptions = {}
        for function in tools:
            documentation = (inspect.getdoc(function) or "").splitlines()
            description = documentation[0] if documentation else "No description"
            tool_descriptions[function.__name__] = description[:120]
        base = list(base_instructions)
        self.model = model
        self.tools = {function.__name__: function for function in tools}
        self.tool_names = tool_names
        self.tool_signatures = tool_signatures
        self.tool_descriptions = tool_descriptions
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
            "Keep the plan minimal and order dependent work correctly. "
            "Choose tool names from the compact catalog in the current prompt. "
            "Tool arguments are generated and validated separately after the plan.\n\n"
            "Tool selection rules:\n"
            "- For Git state or status, use git_status.\n"
            "- Use list_code only to list source entries.\n"
            "- Use read_code only for a specific source file, never a directory.\n"
            "- Repository inspection must use list_code/read_code or list_files/read_file.\n"
            "- Do not add a synthesis, summary, report, or final-response step; the "
            "host produces the response after all tool steps finish.\n"
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

    def _planning_catalog(self, task: str) -> str:
        words = set(re.findall(r"[a-z0-9_]{3,}", task.casefold()))
        aliases = {
            "archivo": "file", "archivos": "file", "codigo": "code",
            "directorio": "directory", "repositorio": "repo",
            "aplicacion": "application", "aplicaciones": "application",
            "memoria": "memory", "correo": "email", "clima": "weather",
            "buscar": "search", "leer": "read", "abrir": "open",
            "sintaxis": "syntax", "configuracion": "config",
        }
        words.update(aliases[word] for word in tuple(words) if word in aliases)
        scored = []
        for name, description in self.tool_descriptions.items():
            searchable = f"{name.replace('_', ' ')} {description}".casefold()
            score = sum(1 for word in words if word in searchable)
            if score:
                scored.append((score, name, description))
        scored.sort(key=lambda item: (-item[0], item[1]))
        names = ", ".join(sorted(self.tool_names))
        details = "\n".join(
            f"- {name}: {description}" for _, name, description in scored[:16]
        )
        return f"Available tool names: {names}\nRelevant tool details:\n{details or '- None'}"

    @staticmethod
    def _source_hints(task: str) -> str:
        words = set(re.findall(r"[a-z0-9_]{4,}", task.casefold()))
        candidates = []
        try:
            completed = subprocess.run(
                ["git", "-C", str(REPOSITORY_ROOT), "ls-files", "*.py"],
                capture_output=True, text=True, errors="replace", timeout=5)
            paths = completed.stdout.splitlines() if completed.returncode == 0 else []
        except (OSError, subprocess.TimeoutExpired):
            paths = []
        for path in paths:
            searchable = Path(path).as_posix().casefold()
            score = sum(
                1 for word in words
                if word[:6] in searchable or searchable.find(word[:4]) >= 0)
            if score:
                candidates.append((score, searchable))
        candidates.sort(key=lambda item: (-item[0], item[1]))
        paths = [path for _, path in candidates[:24]]
        return ", ".join(paths) if paths else "No task-matching source paths found."

    @staticmethod
    def _planning_guidance(task: str) -> str:
        normalized = task.casefold()
        guidance = []
        if ("workspace" in normalized
                and any(term in normalized for term in (
                    "inspect", "explain", "identify", "inspeccion", "explica"))):
            guidance.append(
                "Read src/init/visuals/workspace.py and "
                "src/init/visuals/response.py in separate read_code steps.")
        if ("python" in normalized
                and any(term in normalized for term in (
                    "syntax", "sintaxis", "syntaxe", "sintaxe"))):
            guidance.append(
                "Use execute_command for the actual read-only syntax check. "
                f"Its command will be validated as: {PYTHON_SYNTAX_COMMAND}")
        return "\n".join(guidance) or "No additional task-specific guidance."

    def _argument_model(self, tool_name: str):
        function = self.tools[tool_name]
        signature = self.tool_signatures[tool_name]
        try:
            hints = get_type_hints(function)
        except (NameError, TypeError):
            hints = {}
        fields = {}
        for name, parameter in signature.parameters.items():
            if parameter.kind in {
                    inspect.Parameter.VAR_POSITIONAL,
                    inspect.Parameter.VAR_KEYWORD}:
                continue
            annotation = hints.get(name, parameter.annotation)
            if annotation is inspect.Parameter.empty:
                annotation = Any
            default = (... if parameter.default is inspect.Parameter.empty
                       else parameter.default)
            fields[name] = (annotation, default)
        model_name = "".join(part.title() for part in tool_name.split("_"))
        return create_model(
            f"{model_name}Arguments", __config__=ConfigDict(extra="forbid"),
            **fields)

    async def _plan_arguments(self, task: str, step, trace_model,
                              source_hints: str):
        tool_name = step.tool_name
        normalized_task = task.casefold()
        syntax_request = (
            "python" in normalized_task
            and any(term in normalized_task for term in (
                "syntax", "sintaxis", "syntaxe", "sintaxe")))
        arguments_type = self._argument_model(tool_name)
        signature = self.tool_signatures[tool_name]
        agent = Agent(
            model=trace_model,
            output_type=NativeOutput(
                arguments_type,
                name=f"{tool_name}_arguments",
                description=f"Validated arguments for {tool_name}{signature}.",
                strict=True,
            ),
            retries={"tools": 1, "output": 2},
            instructions=(
                "Generate arguments only for the selected local tool and current "
                "request. Use concrete values, never placeholders or values from "
                "another task. Preserve read-only intent. Return every required "
                f"argument for {tool_name}{signature}."
            ),
        )

        @agent.output_validator
        def validate_arguments(arguments):
            values = arguments.model_dump(mode="json")
            if tool_name == "read_code":
                path = values.get("path", "")
                try:
                    target = (REPOSITORY_ROOT / path).resolve()
                    target.relative_to(REPOSITORY_ROOT)
                    exists = target.is_file()
                except (OSError, ValueError):
                    exists = False
                if not exists:
                    raise ModelRetry(
                        "Choose an existing repository-relative source path from "
                        "SOURCE_PATH_HINTS. The supplied path does not exist.")
            if (tool_name == "execute_command" and syntax_request
                    and values.get("command") != PYTHON_SYNTAX_COMMAND):
                raise ModelRetry(
                    "Use the exact cross-platform read-only syntax command from "
                    "the instructions. Do not use py_compile or compileall.")
            return arguments

        result = await agent.run(
            json.dumps({
                "ORIGINAL_REQUEST": task,
                "PLANNED_STEP": step.model_dump(mode="json"),
                "REQUIRED_SYNTAX_COMMAND": (
                    PYTHON_SYNTAX_COMMAND
                    if tool_name == "execute_command" and syntax_request
                    else None),
                "SOURCE_PATH_HINTS": source_hints,
            }, ensure_ascii=False),
            model_settings={"max_tokens": 512},
        )
        arguments = result.output.model_dump(mode="json")
        self.tool_signatures[tool_name].bind(**arguments)
        return arguments

    async def plan(self, task: str, max_steps: int) -> ExecutionPlan:
        request_id = uuid.uuid4().hex
        trace_model = _PlanningTraceModel(self.model, self.tool_names)
        source_hints = self._source_hints(task)
        planner = Agent(
            model=trace_model,
            output_type=NativeOutput(
                ExecutionPlanDraft,
                name="execution_plan",
                description="A bounded ordered plan using available tools.",
                strict=True,
            ),
            retries={"tools": 1, "output": 2},
            instructions=self.planner_instructions,
        )

        @planner.output_validator
        def validate_execution_plan(plan: ExecutionPlanDraft) -> ExecutionPlanDraft:
            if plan.request_id != request_id:
                raise ModelRetry("Copy REQUEST_ID exactly from the current prompt.")
            if len(plan.steps) > max_steps:
                raise ModelRetry(f"Use no more than {max_steps} steps.")
            step_ids = [step.id for step in plan.steps]
            if len(step_ids) != len(set(step_ids)):
                raise ModelRetry("Every plan step must have a unique id.")
            unknown = sorted({step.tool_name for step in plan.steps
                              if step.tool_name not in self.tool_names})
            if unknown:
                raise ModelRetry(
                    "Use only available tool names. Unknown: "
                    + ", ".join(unknown))
            final_step_terms = {
                "synthesize", "synthesis", "summarize", "summary",
                "final response", "report findings",
            }
            invalid_final_steps = [
                step.id for step in plan.steps
                if any(term in f"{step.title} {step.instruction}".casefold()
                       for term in final_step_terms)
            ]
            if invalid_final_steps:
                raise ModelRetry(
                    "Remove synthesis, summary, report, and final-response steps. "
                    "Only plan evidence-producing tool calls; the host writes the "
                    "final answer after execution.")
            normalized_task = task.casefold()
            syntax_request = (
                "python" in normalized_task
                and any(term in normalized_task for term in (
                    "syntax", "sintaxis", "syntaxe", "sintaxe")))
            if (syntax_request and "execute_command" in self.tool_names
                    and not any(step.tool_name == "execute_command"
                                for step in plan.steps)):
                raise ModelRetry(
                    "This request requires an execute_command step for an actual "
                    "read-only Python syntax check.")
            return plan

        try:
            result = await planner.run(
                f"REQUEST_ID: {request_id}\nORIGINAL_REQUEST:\n{task}\n"
                f"MAXIMUM_STEPS: {max_steps}\n"
                f"{self._planning_catalog(task)}\n"
                f"TASK_SPECIFIC_GUIDANCE:\n{self._planning_guidance(task)}\n"
                f"SOURCE_PATH_HINTS:\n{source_hints}",
                model_settings={"max_tokens": 1024},
            )
            draft = result.output
            steps = []
            for step in draft.steps:
                arguments = await self._plan_arguments(
                    task, step, trace_model, source_hints)
                steps.append(PlanStep(
                    **step.model_dump(mode="json"), tool_args=arguments))
            return ExecutionPlan(
                request_id=draft.request_id, goal=draft.goal, steps=steps)
        except Exception as error:
            errors = _safe_exception_chain(error)
            frames = [
                {"file": Path(frame.filename).name,
                 "line": frame.lineno, "function": frame.name}
                for frame in traceback.extract_tb(error.__traceback__)
            ]
            LOGGER.error(
                "Structured planning failed request=%s attempts=%d "
                "outputs=%s errors=%s traceback=%s",
                request_id[:8], trace_model.attempts,
                trace_model.records[-3:], errors, frames)
            summary = " | ".join(
                f"{item['type']}: {item['detail']}" for item in errors)
            raise PlanningOutputError(summary[:4000]) from None

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
