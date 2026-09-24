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
MAX_PLAN_STEPS = 6


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
            usage = response.usage
            redacted = _redact_output(content, self.tool_names)
            self.records.append({
                "attempt": self.attempts,
                "finish_reason": response.finish_reason,
                "characters": len(content),
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "output": redacted,
            })
            LOGGER.debug(
                "Planning model output attempt=%d finish_reason=%s "
                "characters=%d input_tokens=%s output_tokens=%s output=%s",
                self.attempts, response.finish_reason, len(content),
                usage.input_tokens, usage.output_tokens,
                redacted)
        if response.finish_reason == "length":
            LOGGER.warning(
                "Planning model output truncated attempt=%d characters=%d "
                "input_tokens=%s output_tokens=%s max_tokens=%s",
                self.attempts, sum(len(content) for content in contents),
                response.usage.input_tokens, response.usage.output_tokens,
                model_settings.get("max_tokens"))
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
            "Use no more than six steps. Keep the goal, titles, and instructions "
            "short; do not restate the request or tool catalog. "
            "Choose tool names from the compact catalog in the current prompt. "
            
            "Tool arguments are generated and validated separately after the plan.\n\n"
            "File modification and approval contract:\n"
            "- A request to prepare a change and ask approval BEFORE writing is an "
            "approval-gated write request. Include the real write step; never "
            "replace it with a conversational promise.\n"
            "- If ORIGINAL_REQUEST requests a file change, including approval-gated changes, "
            "include the appropriate registered write tool as an actual plan step. "
            "Do not replace that step with a conversational draft or an approval "
            "request in the final response.\n"
            "- Set requires_approval=true on every file-writing step. The host "
            "persists the exact tool and arguments and pauses before execution. "
            "Including a write step in the plan does NOT execute it.\n"
            "- Never include send_message or another communication tool merely "
            "to request approval. Approval is handled by the host.\n"
            "- For an ADD SECTION request, prefer append_file with only the new section, "
            "not edit_file or create_file. Preserve the existing file verbatim.\n"
            "- When a write operation depends on content that must first be read "
            "or computed, do not invent its contents or claim that a previous "
            "step's output will automatically become a later tool argument. "
            "Only plan an executable write with concrete, valid arguments.\n\n"
            
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

        self.plan_validator_instructions = [*base, (
            "Validate ORIGINAL_REQUEST against PROPOSED_PLAN. "
            "Reject unrelated goals, invented files or tools, unnecessary "
            "side effects, and operations that cannot satisfy the request. "
            "A request to prepare a change and obtain approval before writing "
            "may include the actual write operation in the plan. Planning "
            "that operation does not execute it. "
            "Approval is represented by the PlanStep.requires_approval field, "
            "NOT by an argument passed to the write tool. "
            "For every file-writing step, require requires_approval=true. "
            "The host orchestrator must pause in AWAITING_APPROVAL before "
            "invoking the tool. Never require a send_message step or a "
            "conversational approval request. "
            "Reject missing, placeholder, truncated, or fabricated write "
            "arguments. Do not assume that output from an earlier step "
            "automatically becomes an argument of a later step. "
            "A syntax-check request must execute an actual syntax check. "
            "Repository claims require repository or file inspection evidence. "
            "Return a concise, concrete diagnostic summary."
        )]

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
                "task. Be strict about tool failures and missing required results. "
                "list_code and list_files can filter by suffix and explicitly report "
                "root-only or recursive scope. Treat their successful filtered output, "
                "including a confirmed empty result, as direct evidence; do not demand "
                "that a shell command repeat the search. Never request user approval "
                "or propose an unplanned follow-up operation."
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
                "observations. Never request approval, ask whether to proceed, "
                "or propose executing a step already completed. Approval is "
                "exclusively managed by the host and cannot be requested in a final response."
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
    def _python_file_discovery(task: str) -> str | None:
        normalized = task.casefold()
        python_files = (
            ("python" in normalized or ".py" in normalized)
            and any(term in normalized for term in (
                "list", "find", "show", "lista", "buscar", "muestra")))
        if not python_files:
            return None
        if any(term in normalized for term in (
                "recursive", "recursively", "every directory", "all directories",
                "entire project", "whole project", "cada directorio",
                "todos los directorios", "proyecto entero", "todo el proyecto")):
            return "recursive"
        if any(term in normalized for term in (
                "project root", "root of the project", "repository root",
                "raíz del proyecto", "raiz del proyecto", "raíz del repositorio",
                "raiz del repositorio")):
            return "root"
        return "root"

    @staticmethod
    def _planning_guidance(task: str) -> str:
        normalized = task.casefold()
        guidance = []
        discovery = PydanticAgentBackend._python_file_discovery(task)
        if discovery == "recursive":
            guidance.append(
                "Use list_code with directory='.', recursive=true, suffix='.py'. "
                "This searches nested source directories with the existing tool; "
                "do not use execute_command or ask for approval.")
        elif discovery == "root":
            guidance.append(
                "Use list_code with directory='.', recursive=false, suffix='.py'. "
                "Root-only means do not include files from nested directories.")
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

    async def _plan_arguments(self, task: str, step,
            trace_model, source_hints: str):
        """Generate arguments for a planned tool using its registered schema."""
        tool_name = step.tool_name
        if tool_name not in self.tools:
            raise PlanningOutputError(
                f"Unregistered tool: {tool_name}")

        arguments_type = self._argument_model(tool_name)
        signature = self.tool_signatures[tool_name]

        agent = Agent(
            model=trace_model,
            output_type=NativeOutput(
                arguments_type,
                name=f"{tool_name}_arguments",
                description=(
                    f"Validated arguments for {tool_name}{signature}."),
                strict=True),
            retries={
                "tools": 1,
                "output": 2,
            },
            instructions=(
                "Generate arguments for the selected tool using its "
                "registered schema. Use only the current request, "
                "planned step, and available execution context. "
                "Preserve the user's requested operation and scope. "
                "Do not incorporate surrounding instructions into "
                "file paths or other resource identifiers. "
                "Do not invent missing resources or substitute "
                "unrelated resources. Return every required argument."
            ))

        @agent.output_validator
        def validate_arguments(arguments):
            values = arguments.model_dump(mode="json")

            try:
                signature.bind(**values)
            except TypeError as error:
                raise ModelRetry(
                    f"Arguments do not match the "
                    f"tool signature: {error}") from error

            return arguments

        context = {
            "ORIGINAL_REQUEST": task,
            "PLANNED_STEP": step.model_dump(mode="json"),
            "SOURCE_PATH_HINTS": source_hints,
        }

        result = await agent.run(
            json.dumps(
                context,
                ensure_ascii=False,
            ),
            model_settings={"max_tokens": 2048,})

        arguments = result.output.model_dump(mode="json")

        signature.bind(**arguments)
        return arguments

    async def plan(self, task: str,
            max_steps: int) -> ExecutionPlan:
        """Generate and validate a bounded execution plan."""

        if not task.strip():
            raise ValueError("The task must not be empty.")

        if max_steps < 1:
            raise ValueError("max_steps must be greater than zero.")

        request_id = uuid.uuid4().hex
        plan_step_limit = min(max_steps, MAX_PLAN_STEPS)

        trace_model = _PlanningTraceModel(
            self.model,
            self.tool_names)

        source_hints = self._source_hints(task)

        planner = Agent(
            model=trace_model,
            output_type=NativeOutput(
                ExecutionPlanDraft,
                name="execution_plan",
                description="A bounded ordered plan using available tools.",
                strict=True),
            retries={
                "tools": 1,
                "output": 2,
            },
            instructions=self.planner_instructions)

        @planner.output_validator
        def validate_execution_plan(
                plan: ExecutionPlanDraft) -> ExecutionPlanDraft:
            if plan.request_id != request_id:
                raise ModelRetry(
                    "The request ID does not match the current request.")

            if not 1 <= len(plan.steps) <= plan_step_limit:
                raise ModelRetry(
                    f"The plan must contain between 1 and "
                    f"{plan_step_limit} steps.")

            step_ids = [step.id for step in plan.steps]

            if len(step_ids) != len(set(step_ids)):
                raise ModelRetry(
                    "Every plan step must have a unique ID.")

            unknown_tools = {
                step.tool_name
                for step in plan.steps
                if step.tool_name not in self.tool_names
            }

            if unknown_tools:
                raise ModelRetry(
                    "The plan contains unregistered tools: "
                    + ", ".join(sorted(unknown_tools)))

            return plan

        try:
            result = await planner.run((
                    f"REQUEST_ID: {request_id}\n"
                    f"ORIGINAL_REQUEST:\n{task}\n"
                    f"MAXIMUM_STEPS: {plan_step_limit}\n"
                    f"{self._planning_catalog(task)}\n"
                    f"SOURCE_PATH_HINTS:\n{source_hints}"),
                model_settings={
                    "max_tokens": 2048,
                })

            draft = result.output
            print(
                "[FORGE PLAN]",
                json.dumps(
                    {
                        "request_id": request_id,
                        "task": task,
                        "goal": draft.goal,
                        "steps": [
                            step.model_dump(mode="json")
                            for step in draft.steps
                        ],
                        "source_hints": source_hints,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                flush=True,
            )
            steps = []

            for step in draft.steps:
                arguments = await self._plan_arguments(
                    task,
                    step,
                    trace_model,
                    source_hints)

                steps.append(
                    PlanStep(
                        **step.model_dump(mode="json"),
                        tool_args=arguments))

            return ExecutionPlan(
                request_id=draft.request_id,
                goal=draft.goal,
                steps=steps,
            )

        except Exception as error:
            errors = _safe_exception_chain(error)

            frames = [
                {
                    "file": Path(frame.filename).name,
                    "line": frame.lineno,
                    "function": frame.name,
                }
                for frame in traceback.extract_tb(error.__traceback__)
            ]

            LOGGER.error(
                "Structured planning failed request=%s attempts=%d "
                "outputs=%s errors=%s traceback=%s",
                request_id[:8],
                trace_model.attempts,
                trace_model.records[-3:],
                errors,
                frames)

            summary = " | ".join(
                f"{item['type']}: {item['detail']}"
                for item in errors)

            raise PlanningOutputError(
                summary[:4000]) from error

    async def validate_plan(self, task: str,
                            plan: ExecutionPlan) -> VerificationResult:
        """Enforce execution invariants in Python, not with an LLM judge."""
        write_tools = {
            "create_file", "edit_file", "append_file", "replace_in_file",
            "write_binary_file",
        }
        if not plan.steps or len(plan.steps) > MAX_PLAN_STEPS:
            return VerificationResult(success=False, summary="Invalid step count")
        if len({step.id for step in plan.steps}) != len(plan.steps):
            return VerificationResult(success=False, summary="Duplicate step IDs")
        # An approval request is not satisfied by a conversational draft.
        approval_requested = any(term in task.casefold() for term in (
            "aprobación", "aprobacion", "aprue", "approval", "confirmación",
            "confirmacion", "before writing", "antes de escribir"))
        file_change_requested = any(term in task.casefold() for term in (
            "modific", "edit", "escrib", "write", "añad", "add", "crea",
            "create", "reemplaz", "replace", "append"))
        if approval_requested and file_change_requested and not any(
                step.tool_name in write_tools for step in plan.steps):
            return VerificationResult(success=False,
                                      summary="Approval requested but no real write step was planned")
        for step in plan.steps:
            if step.tool_name not in self.tools:
                return VerificationResult(success=False,
                                          summary=f"Unknown tool: {step.tool_name}")
            try:
                self.tool_signatures[step.tool_name].bind(**step.tool_args)
                self._argument_model(step.tool_name).model_validate(step.tool_args)
            except (TypeError, ValueError, ValidationError) as error:
                return VerificationResult(success=False,
                                          summary=f"Invalid arguments for {step.tool_name}: {error}")
            if step.tool_name in write_tools:
                if ("añad" in task.casefold() or "append" in task.casefold()
                        or "add section" in task.casefold()) and step.tool_name != "append_file":
                    return VerificationResult(success=False,
                                              summary="Adding a section requires append_file, not file replacement")
                if not step.requires_approval:
                    return VerificationResult(success=False,
                                              summary=f"Write step {step.id} lacks approval")
                if not any(term in task.casefold() for term in (
                        "modific", "edit", "escrib", "write", "añad", "add",
                        "crea", "create", "reemplaz", "replace", "append")):
                    return VerificationResult(success=False,
                                              summary="Unrequested file write")
                for name, value in step.tool_args.items():
                    if isinstance(value, str) and name in {
                            "content", "text", "new_content", "replacement"}:
                        if not value.strip() or value.rstrip().endswith(("```", "\\")):
                            return VerificationResult(success=False,
                                                      summary="Empty or incomplete write content")
            if step.tool_name == "change_directory":
                path = step.tool_args.get("path")
                if not isinstance(path, str) or not Path(path).expanduser().is_dir():
                    return VerificationResult(success=False,
                                              summary="Directory does not exist")
        return VerificationResult(success=True, summary="Plan invariants validated")

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
