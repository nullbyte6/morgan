#  Copyright (c) 2026 Diego.
#
#  SPDX-License-Identifier: GPL-3.0-or-later
#
#  This file is part of arlo.
"""Validated quick-command groups backed by the user's commands.json."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from .config import HOME_PATH


COMMANDS_FILE = HOME_PATH / "json" / "commands.json"
TOOL_ALIASES = {
    "open_app": "open_application",
    "minimize_all": "minimize_all_windows",
}


def _action(action, index: int) -> dict:
    if isinstance(action, str):
        tool, separator, value = action.partition(":")
        tool = tool.strip()
        if not tool:
            raise ValueError(f"action {index} has no tool name")
        normalized = {"tool": tool, "arguments": {}}
        if separator:
            normalized["value"] = value.strip()
        return normalized

    if not isinstance(action, dict):
        raise ValueError(f"action {index} must be a string or object")
    tool = action.get("tool")
    arguments = action.get("arguments", {})
    if not isinstance(tool, str) or not tool.strip():
        raise ValueError(f"action {index} has no tool name")
    if not isinstance(arguments, dict):
        raise ValueError(f"action {index} arguments must be an object")
    return {"tool": tool.strip(), "arguments": arguments}


def load_quick_commands(path: Path = COMMANDS_FILE) -> dict[str, dict]:
    """Load and validate quick commands without caching user-owned data."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as error:
        raise ValueError(f"Quick-command file not found: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Invalid quick-command JSON at line {error.lineno}, "
            f"column {error.colno}: {error.msg}") from error

    if not isinstance(payload, dict):
        raise ValueError("commands.json must contain an object")
    commands = payload.get("quick_commands")
    if not isinstance(commands, dict):
        raise ValueError("commands.json must contain a quick_commands object")

    validated = {}
    for name, definition in commands.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Quick-command names must be non-empty strings")
        if not isinstance(definition, dict):
            raise ValueError(f"Quick command {name!r} must be an object")
        actions = definition.get("actions")
        if not isinstance(actions, list) or not actions:
            raise ValueError(
                f"Quick command {name!r} must contain a non-empty actions list")
        description = definition.get("description", "")
        if not isinstance(description, str):
            raise ValueError(
                f"Quick command {name!r} description must be text")
        validated[name] = {
            "description": description.strip(),
            "actions": [
                _action(action, index)
                for index, action in enumerate(actions, start=1)
            ],
        }
    return validated


def list_quick_commands() -> str:
    """List user-defined quick commands and their ordered actions."""
    try:
        commands = load_quick_commands()
        return json.dumps({
            "status": "completed",
            "commands_file": str(COMMANDS_FILE),
            "quick_commands": commands,
        }, ensure_ascii=False)
    except (OSError, UnicodeError, ValueError) as error:
        return json.dumps({
            "status": "error",
            "commands_file": str(COMMANDS_FILE),
            "error": str(error),
        }, ensure_ascii=False)


def _prepare_actions(actions: list[dict], registry: dict) -> list[tuple]:
    """Resolve and bind every action before the first one is executed."""
    prepared = []
    for index, action in enumerate(actions, start=1):
        requested_name = action["tool"]
        tool_name = TOOL_ALIASES.get(requested_name, requested_name)
        if tool_name == "run_quick_command":
            raise ValueError("Quick commands cannot recursively run quick commands")
        function = registry.get(tool_name)
        if function is None:
            raise ValueError(
                f"action {index} references unavailable tool {requested_name!r}")

        arguments = action["arguments"]
        if "value" in action:
            if arguments:
                raise ValueError(
                    f"action {index} cannot combine a compact value and arguments")
            bound = inspect.signature(function).bind(action["value"])
        else:
            bound = inspect.signature(function).bind(**arguments)
        prepared.append((index, requested_name, tool_name, function, bound))
    return prepared


def _result_failed(value) -> bool:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return value.strip().casefold().startswith("error")
    return (isinstance(value, dict)
            and value.get("status") in {"error", "failed", "timeout", "denied"})


def run_quick_command(name: str) -> str:
    """Run one commands.json group through Arlo's registered tools in order.

    All actions are resolved and their arguments validated before execution.
    Existing tool safeguards and confirmations remain active. Runtime failures
    are reported per action and do not hide results from the remaining actions.
    """
    context = {"quick_command": name, "commands_file": str(COMMANDS_FILE)}
    try:
        commands = load_quick_commands()
        matches = [key for key in commands if key.casefold() == name.strip().casefold()]
        if len(matches) != 1:
            available = sorted(commands, key=str.casefold)
            raise ValueError(
                f"Unknown quick command {name!r}; available: {available}")
        command_name = matches[0]
        definition = commands[command_name]

        from .tools import TOOLS
        registry = {tool.__name__: tool for tool in TOOLS}
        prepared = _prepare_actions(definition["actions"], registry)
    except (OSError, TypeError, UnicodeError, ValueError) as error:
        return json.dumps({
            **context,
            "status": "error",
            "error": str(error),
        }, ensure_ascii=False)

    results = []
    failures = 0
    for index, requested_name, tool_name, function, bound in prepared:
        try:
            output = function(*bound.args, **bound.kwargs)
            failed = _result_failed(output)
            failures += int(failed)
            results.append({
                "index": index,
                "action": requested_name,
                "tool": tool_name,
                "status": "failed" if failed else "completed",
                "output": output,
            })
        except Exception as error:
            failures += 1
            results.append({
                "index": index,
                "action": requested_name,
                "tool": tool_name,
                "status": "failed",
                "error": str(error),
            })

    return json.dumps({
        **context,
        "quick_command": command_name,
        "description": definition["description"],
        "status": "completed" if not failures else "partial",
        "completed_actions": len(results) - failures,
        "failed_actions": failures,
        "results": results,
    }, ensure_ascii=False, default=str)
