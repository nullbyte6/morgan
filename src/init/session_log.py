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
"""Conversation context, artifacts, budgets and daily Markdown logs."""

import base64
import copy
import hashlib
import io
import json
import logging
import math
import re
import uuid
import wave
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from .config import HOME_PATH, ensure_storage
from .identity import get_assistant
from .lang import tr
from .output import markdown_text

SESSION_NAME = re.compile(r"\d{4}-\d{2}-\d{2}\.md")
DIRECTORY_COMMAND = re.compile(r"cd(?:\s+.*)?", re.IGNORECASE | re.DOTALL)
MAX_DAYS = 24
_current_session_path: Path | None = None


def is_local_command(text: str) -> bool:
    """Whether text is a directory change or module reload handled without the model."""
    from .hot_reload import is_reload_command
    return DIRECTORY_COMMAND.fullmatch(text.strip()) is not None or is_reload_command(text)


def _session_logs(directory: Path) -> list[Path]:
    logs = []
    for path in directory.iterdir():
        if (SESSION_NAME.fullmatch(path.name) and not path.is_symlink()
                and path.is_file()):
            try:
                with path.open(encoding="utf-8-sig") as log:
                    first_line = log.readline().strip()
            except (OSError, UnicodeError):
                continue
            if re.fullmatch(r".+ Log — " + re.escape(path.stem), first_line):
                logs.append(path)
    return logs


def clear_logs(directory: Path | None = None) -> None:
    """Delete every daily Markdown conversation log."""
    directory = (Path(directory) if directory is not None else HOME_PATH / ".log").resolve()
    if directory.is_dir():
        for path in _session_logs(directory):
            path.unlink(missing_ok=True)


def open_current_session_log() -> str:
    """Open this the assistant process's current session log in the default application."""
    from .brain import open_file

    if _current_session_path is None:
        return tr("session.none")
    return open_file(str(_current_session_path))


TOOL_ARTIFACT_MIN_BYTES = 4096


def message_status(lifecycle):
    """Translate task lifecycle to the independent conversation persistence domain."""
    status = str(lifecycle)
    if status in {"complete", "completed"}:
        return "completed"
    if status in {"active", "waiting", "blocked", "interrupted", "cancelled"}:
        return "interrupted"
    if status in {"limit_reached", "failed", "error"}:
        return "error"
    raise ValueError(f"Unknown conversation lifecycle: {status}")


class SessionContext:
    """Conversation state and external artifacts for one live session."""

    def __init__(self, session_id: str, directory: Path):
        self.session_id = session_id
        self.messages = []
        self.task_controller = None
        self.task_state = None
        self.cancellation_token = None
        self.working_directory = str(Path.cwd())
        self.artifact_paths = set()
        self.directory = Path(directory).resolve() / "artifacts" / session_id

    def add_exchange(self, prompt: str, reply: str):
        from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
        self.messages.extend((ModelRequest(parts=[UserPromptPart(prompt)]),
                              ModelResponse(parts=[TextPart(reply)])))

    def _store(self, content: str, extension: str, label: str) -> str:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{uuid.uuid4().hex}{extension}"
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        self.artifact_paths.add(str(path.resolve()))
        return f"[{label}]({path.as_posix()})"

    def externalize_messages(self, messages):
        from pydantic_ai.messages import ToolReturnPart
        result = copy.deepcopy(list(messages))
        for message in result:
            for part in message.parts:
                if isinstance(part, ToolReturnPart):
                    if isinstance(part.content, str):
                        raw = part.content
                    else:
                        raw = json.dumps(part.content, ensure_ascii=False, indent=2,
                                         default=str)
                    if len(raw.encode("utf-8")) >= TOOL_ARTIFACT_MIN_BYTES:
                        extension = ".json" if raw.lstrip().startswith(("{", "[")) else ".txt"
                        part.content = self._store(
                            raw, extension, f"Tool result: {part.tool_name}")
        return result


def _context_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class ContextBudget:
    """Measure and compact agent context without requiring task state."""

    def __init__(self, context, trace=None):
        self.context = context
        self.artifacts = {}
        self.trace = trace if trace is not None else lambda event, **details: None

    def archive(self, raw, label):
        key = hashlib.sha256(_context_json(raw).encode("utf-8")).hexdigest()
        if key not in self.artifacts:
            self.artifacts[key] = self.context._store(raw, ".json", label)
        return self.artifacts[key]

    def tool_result_reference(self, part):
        raw = _context_json(part.content)
        return {"artifact": self.archive(raw, f"Tool return {part.tool_call_id}"),
                "digest": hashlib.sha256(raw.encode("utf-8")).hexdigest(), "tool": part.tool_name,
                "call_id": part.tool_call_id, "characters": len(raw),
                "read": {"tool": "read_file", "offset": 0, "limit": 2000}}

    @staticmethod
    def reserve(context, completion, recovery_attempts=0):
        completion = min(completion, max(512, context // 3))
        margin = max(1024, math.ceil(context * 0.20))
        input_limit = context - completion - margin - min(recovery_attempts * 1024, context // 8)
        return completion, margin, input_limit

    async def measure_request(self, request_context, messages, *, token_scale=1.0):
        from pydantic_ai._agent_graph import _clean_message_history
        model = request_context.model
        settings = {**(model.settings or {}), **(request_context.model_settings or {})}
        parameters = request_context.model_request_parameters
        settings, parameters = model.prepare_request(settings, parameters)
        normalized = _clean_message_history(messages, repair_last_response=True)
        prepared = model.prepare_messages(normalized, parameters)
        normalized = _clean_message_history(prepared, repair_last_response=True)
        mapped = await model._map_messages(normalized, parameters, model_settings=settings)
        tools, _ = model._get_tool_choice(settings or {}, parameters)
        components = {"messages": len(_context_json(mapped).encode("utf-8")),
                      "tool_schemas": len(_context_json(tools).encode("utf-8"))}
        if parameters.output_object is not None:
            components["output_schema"] = len(_context_json(model._map_json_schema(parameters.output_object)).encode("utf-8"))
        audio_bytes = audio_tokens = 0
        for message in mapped:
            content = message.get("content")
            for part in content if isinstance(content, list) else []:
                if not isinstance(part, dict) or part.get("type") != "input_audio":
                    continue
                audio = part.get("input_audio", {})
                if audio.get("format") != "wav" or not isinstance(audio.get("data"), str):
                    continue
                try:
                    with wave.open(io.BytesIO(base64.b64decode(audio["data"], validate=True)), "rb") as wav:
                        duration = wav.getnframes() / wav.getframerate()
                    if duration > 0:
                        audio_bytes += len(audio["data"])
                        audio_tokens += math.ceil(duration * 50) + 128
                except (ValueError, EOFError, wave.Error):
                    continue
        proxy = math.ceil((sum(components.values()) - audio_bytes) / 4) + 32 * len(mapped) + 256 + audio_tokens
        return {"estimated_input_tokens": math.ceil(proxy * token_scale),
                "estimator": ("provider_json_utf8_div4_with_wav_duration_and_usage_calibration"
                              if audio_bytes else "provider_json_utf8_div4_with_framing_and_usage_calibration"),
                "estimator_scale": token_scale, "unscaled_input_tokens": proxy,
                "component_bytes": components, "audio_tokens": audio_tokens}

    async def compact(self, messages, measure, input_limit, *, force=False, externalize_tool_result=None):
        from pydantic_ai.messages import ModelRequest, ModelMessagesTypeAdapter, UserPromptPart

        result = copy.deepcopy(messages)
        before = (await measure(result))["estimated_input_tokens"]
        if before <= input_limit and not force:
            return result
        latest_response = next((index for index in range(len(result) - 1, -1, -1)
                                if result[index].kind == "response"), len(result))
        externalized = []
        for message in result[:latest_response]:
            if externalized and not force and (await measure(result))["estimated_input_tokens"] <= input_limit:
                break
            for part in message.parts:
                if part.part_kind == "tool-return" and len(_context_json(part.content)) > 2000 and not (
                        isinstance(part.content, dict) and "artifact" in part.content and "data" not in part.content):
                    content = externalize_tool_result(part) if externalize_tool_result is not None else None
                    part.content = self.tool_result_reference(part) if content is None else content
                    externalized.append(part.tool_call_id)
        after = (await measure(result))["estimated_input_tokens"]
        archive = None
        boundary = 0
        if after > input_limit or force:
            pending = set()
            boundaries = []
            for index, message in enumerate(result):
                for part in message.parts:
                    if part.part_kind == "tool-call":
                        pending.add(part.tool_call_id)
                    elif part.part_kind in ("tool-return", "retry-prompt"):
                        pending.discard(getattr(part, "tool_call_id", None))
                if not pending:
                    boundaries.append(index + 1)
            if not force and latest_response < len(result) and any(
                    part.part_kind == "tool-call" for part in result[latest_response].parts):
                boundaries = [boundary for boundary in boundaries if boundary <= latest_response]
            user_indices = [index for index, message in enumerate(result)
                            if message.kind == "request" and any(
                                part.part_kind == "user-prompt" and not (
                                    isinstance(part.content, str) and part.content.startswith("Earlier context archived"))
                                for part in message.parts)]
            preserved = {}
            for index in user_indices[-2:]:
                preserved[index] = replace(result[index], parts=[part for part in result[index].parts
                                           if part.part_kind == "user-prompt" and not (
                                               isinstance(part.content, str) and part.content.startswith("Earlier context archived"))])
            if len(user_indices) > 1:
                previous_response = next((index for index in range(user_indices[-1] - 1, user_indices[-2], -1)
                                          if result[index].kind == "response" and any(
                                              part.part_kind == "text" for part in result[index].parts)
                                          and not any(part.part_kind == "tool-call" for part in result[index].parts)), None)
                if previous_response is not None:
                    preserved[previous_response] = result[previous_response]
            archive = self.archive(ModelMessagesTypeAdapter.dump_json(messages).decode(), "Earlier conversation and tool evidence")
            pointer = ModelRequest(parts=[UserPromptPart("Earlier context archived without discarding evidence: " + archive)])
            for candidate in boundaries:
                suffix = [preserved[index] for index in sorted(preserved) if index < candidate]
                suffix.extend(result[candidate:])
                retained = [pointer, *suffix]
                estimate = (await measure(retained))["estimated_input_tokens"]
                if estimate < after:
                    chosen, chosen_size, boundary = retained, estimate, candidate
                    if estimate <= input_limit and (not force or estimate < before):
                        break
            if boundary:
                result, after = chosen, chosen_size
        if after < before:
            self.trace("context_compacted", reason="recovery" if force else "preventive_budget",
                       estimated_input_before=before, estimated_input_after=after,
                       input_limit=input_limit, budget_satisfied=after <= input_limit,
                       archived_messages=boundary, retained_messages=len(result),
                       externalized_tool_calls=externalized, archive=archive)
        return result


class SessionLog:
    def __init__(self, directory=None, *, memory_service=None):
        self.private = False
        self.session_id = uuid.uuid4().hex
        context_directory = Path(directory) if directory is not None else HOME_PATH / ".log"
        self.context = SessionContext(self.session_id, context_directory)
        self.started_at = datetime.now().astimezone().isoformat()
        self.last_user_message_id = None
        self.last_user_text = ""
        self.memory_error = None
        self._memory_service = memory_service
        self._use_configured_memory = directory is None
        if directory is None:
            ensure_storage()
        self.directory = (Path(directory) if directory is not None
                          else HOME_PATH / ".log").resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self._start_day(datetime.now().astimezone())

    def handle_command(self, command):
        """Handle local privacy controls before recording or sending input."""
        parts = command.strip().casefold().split()
        if not parts or parts[0] not in ("/private", "/private"):
            return None
        action = parts[1] if len(parts) == 2 else "toggle" if len(parts) == 1 else ""
        if action == "toggle":
            self.private = not self.private
        elif action in ("on", "off"):
            self.private = action == "on"
        elif action != "status":
            return tr("privacy.usage")
        return tr("privacy.on" if self.private else "privacy.off")

    def _start_day(self, started):
        self.path = self.directory / f"{started:%Y-%m-%d}.md"
        try:
            log = self.path.open("x", encoding="utf-8")
        except FileExistsError:
            pass
        else:
            with log:
                session_header = f"{get_assistant().name} Log — {started:%Y-%m-%d}"
                log.write(session_header)
        self._prune()
        global _current_session_path
        _current_session_path = self.path

    def _prune(self):
        logs = _session_logs(self.directory)
        oldest = sorted((path for path in logs if path != self.path),
                        key=lambda path: path.name)
        for path in oldest[:max(0, len(logs) - MAX_DAYS)]:
            if path.resolve().parent != self.directory:
                raise OSError(tr('session_log.session_log_resolved_outside_the_log_directory'))
            path.unlink()

    def write(self, role, text, *, status="completed"):
        """Append Markdown while retaining fenced code in the conversation."""
        if self.private:
            return

        status = message_status(status)
        text = markdown_text(text) if text else ""
        if not text.strip():
            return

        role = " ".join(str(role).splitlines()).strip()
        now = datetime.now().astimezone()
        if self.path.name != f"{now:%Y-%m-%d}.md" or not self.path.exists():
            self._start_day(now)

        original = text
        with self.path.open("a", encoding="utf-8") as log:
            log.write("\n\n")
            source_ref = str(self.path) + "#byte=" + str(log.tell())
            log.write(f"[{now:%H:%M:%S %z}] \n{role}: {text}")
        assistant = get_assistant()
        canonical_role = ("assistant" if role == assistant.name else
                          "system" if role == "System" else "user")
        if canonical_role == "user":
            self.last_user_text = original
            self.last_user_message_id = None
        try:
            service = self._get_memory_service()
            if service is None:
                return
            if self._use_configured_memory:
                from .config import load_config
                if not load_config()["memory"]["store_history"]:
                    return
            service.start_session(session_id=self.session_id, started_at=self.started_at,
                                  metadata={"log_directory": str(self.directory)})
            message_id = service.record_message(self.session_id, canonical_role, original,
                                                created_at=now.isoformat(), status=status,
                                                source_ref=source_ref)
            if canonical_role == "user":
                self.last_user_message_id = message_id
            self.memory_error = None
        except Exception as error:
            self.memory_error = str(error)
            logging.getLogger("assistant.memory").exception("Conversation retained in Markdown; database persistence failed")

    def _get_memory_service(self):
        if self._use_configured_memory:
            from .memory.integration import configured_service
            return configured_service()
        return self._memory_service

    @contextmanager
    def memory_scope(self):
        from .memory.integration import MemoryTurn, active_memory
        service = None
        if not self.private:
            try:
                service = self._get_memory_service()
            except Exception as error:
                self.memory_error = str(error)
                logging.getLogger("assistant.memory").exception("Memory tools unavailable")
        token = active_memory.set(MemoryTurn(service, self.session_id,
                                            self.last_user_message_id, self.last_user_text,
                                            self.private, self.memory_error))
        try:
            yield
        finally:
            active_memory.reset(token)

    def close(self):
        try:
            service = self._get_memory_service()
            if service is not None:
                service.end_session(self.session_id)
        except Exception as error:
            self.memory_error = str(error)
            logging.getLogger("assistant.memory").exception("Memory session could not be closed")

