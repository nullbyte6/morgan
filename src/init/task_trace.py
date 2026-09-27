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
"""Incremental task journals with content-addressed payloads and deterministic replay."""

import copy
import hashlib
import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path


active_model_request = ContextVar("arlo_model_request_trace", default=None)


def serialized_metrics(raw):
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    return {"characters": len(raw.decode("utf-8")), "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest()}


def payload_metrics(value):
    return serialized_metrics(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def settings_metadata(settings):
    return {key: settings[key] for key in (
        "max_tokens", "max_completion_tokens", "thinking", "temperature", "top_p", "seed",
        "openai_reasoning_effort", "parallel_tool_calls") if key in settings
        and isinstance(settings[key], (str, int, float, bool, type(None)))}


async def trace_provider_request(request):
    correlation = active_model_request.get()
    if correlation is None or not correlation.get("request_id") or request.url.path.rstrip("/").split("/")[-1] != "completions":
        return
    correlation["transport_attempt"] += 1
    identity = {key: correlation[key] for key in ("request_id", "request_ordinal", "transport_attempt")}
    trace = correlation["trace"]
    try:
        raw = request.content
        body = json.loads(raw)
        messages = body.get("messages", [])
        tools = body.get("tools", [])
        tool_choice = body.get("tool_choice")
        if isinstance(tool_choice, dict):
            name = tool_choice.get("function", {}).get("name")
            tool_choice = {"type": tool_choice.get("type"),
                           "function": name if name in correlation["tool_names"] else None}
        elif tool_choice not in (None, "auto", "none", "required"):
            tool_choice = None
        controls = {key: body[key] for key in (
            "reasoning_effort", "think", "thinking", "temperature", "top_p", "seed",
            "parallel_tool_calls", "stream") if key in body
            and isinstance(body[key], (str, int, float, bool, type(None)))}
        options = body.get("options")
        if isinstance(options, dict):
            controls["options"] = {key: options[key] for key in ("num_ctx", "num_predict", "think")
                                   if key in options and isinstance(options[key], (int, bool, type(None)))}
        trace("provider_request", **identity, model=body.get("model"),
              token_limits={key: body[key] for key in ("max_tokens", "max_completion_tokens", "num_predict")
                            if key in body and isinstance(body[key], (int, type(None)))},
              controls=controls, tool_choice=tool_choice, wire_payload=serialized_metrics(raw),
              message_count=len(messages), messages=payload_metrics(messages),
              tool_count=len(tools), tools=payload_metrics(tools),
              response_format=payload_metrics(body["response_format"]) if "response_format" in body else None,
              component_serialization="canonical_json_utf8")
    except Exception as error:
        trace("provider_request_measurement_unavailable", **identity, error_type=type(error).__name__)


def response_metrics(response, parameters):
    thinking = [part for part in response.parts if part.part_kind == "thinking"]
    text = [part for part in response.parts if part.part_kind == "text"]
    calls = [part for part in response.parts if part.part_kind == "tool-call"]
    names = {tool.name for tool in [*parameters.function_tools, *parameters.output_tools]}
    usage = response.usage
    return {"provider_response_id": response.provider_response_id,
            "provider_finish_reason": (response.provider_details or {}).get("finish_reason"),
            "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
            "total_tokens": usage.input_tokens + usage.output_tokens,
            "usage_source": "pydantic_ai_request_usage; zero_can_mean_unavailable",
            "total_tokens_source": "input_plus_output",
            "reasoning_tokens": usage.details.get("reasoning_tokens"),
            "thinking_part_count": len(thinking),
            "thinking_characters": sum(len(part.content) for part in thinking),
            "text_part_count": len(text), "visible_text_characters": sum(len(part.content) for part in text),
            "tool_call_part_count": len(calls),
            "tool_call_names": sorted({part.tool_name for part in calls if part.tool_name in names}),
            "unknown_tool_call_count": sum(part.tool_name not in names for part in calls),
            "tool_argument_characters": sum(len(part.args_as_json_str()) for part in calls),
            "recovery_actionable": response.finish_reason != "length" and bool(calls),
            "length_cause": "unavailable_at_provider_boundary" if response.finish_reason == "length" else None}


def measurement_error(trace, event, error, **identity):
    logging.getLogger("assistant.task_control").warning("Model trace measurement unavailable: %s", type(error).__name__)
    trace(event, **identity, error_type=type(error).__name__)


def _changes(previous, current, path=()):
    if isinstance(previous, dict) and isinstance(current, dict):
        for key in previous.keys() - current.keys():
            yield {"op": "remove", "path": [*path, key]}
        for key, value in current.items():
            if key not in previous:
                yield {"op": "set", "path": [*path, key], "value": value}
            else:
                yield from _changes(previous[key], value, (*path, key))
    elif previous != current:
        if isinstance(previous, list) and isinstance(current, list) and current[:len(previous)] == previous:
            yield {"op": "append", "path": list(path), "value": current[len(previous):]}
        else:
            yield {"op": "set", "path": list(path), "value": current}


class TaskJournal:
    def __init__(self, path, state):
        self.path = Path(path)
        self.state = state
        self.previous = {}
        self.event_sequence = 0

    def _payload(self, value):
        def default(item):
            return item.model_dump(mode="json") if hasattr(item, "model_dump") else str(item)
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=default).encode("utf-8")
        if len(raw) <= 8192:
            return json.loads(raw)
        value = json.loads(raw)
        if isinstance(value, dict):
            value = {key: self._payload(child) for key, child in value.items()}
        elif isinstance(value, list):
            value = [self._payload(child) for child in value]
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
        if len(raw) <= 8192:
            return value
        digest = hashlib.sha256(raw).hexdigest()
        target = self.path.parent / ("payload-" + digest + ".json")
        if not target.exists():
            target.write_bytes(raw)
        return {"journal_blob_sha256": digest, "bytes": len(raw)}

    def record(self, event, **details):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        snapshot = self.state.snapshot(include_evidence=False)
        delta = list(_changes(self.previous, snapshot))
        entry = {"version": 2, "task_id": self.state.id, "event_sequence": self.event_sequence + 1,
                 "time": datetime.now(timezone.utc).isoformat(), "event": event,
                 "state_delta": [self._payload(operation) for operation in delta],
                 **{key: self._payload(value) for key, value in details.items()}}
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        self.previous = copy.deepcopy(snapshot)
        self.event_sequence += 1


def replay_trace(path):
    path = Path(path)
    state = {}
    evidence = {}

    def payload(value):
        if isinstance(value, dict) and set(value) == {"journal_blob_sha256", "bytes"}:
            digest = value["journal_blob_sha256"]
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("Invalid journal payload hash")
            raw = (path.parent / ("payload-" + digest + ".json")).read_bytes()
            if hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError("Journal payload hash mismatch")
            return payload(json.loads(raw))
        if isinstance(value, dict):
            return {key: payload(child) for key, child in value.items()}
        if isinstance(value, list):
            return [payload(child) for child in value]
        return value

    with path.open(encoding="utf-8") as stream:
        for sequence, line in enumerate(stream, 1):
            event = json.loads(line)
            if event.get("version") != 2 or event["event_sequence"] != sequence:
                raise ValueError("Unsupported or discontinuous task journal")
            for encoded in event["state_delta"]:
                operation = payload(encoded)
                target = state
                for key in operation["path"][:-1]:
                    target = target[key]
                key = operation["path"][-1]
                if operation["op"] == "remove":
                    del target[key]
                elif operation["op"] == "append":
                    target[key].extend(operation["value"])
                else:
                    target[key] = operation["value"]
            if event["event"] == "observation":
                item = payload(event["evidence"])
                evidence[item["id"]] = item
    return {"state": state, "evidence": evidence}
