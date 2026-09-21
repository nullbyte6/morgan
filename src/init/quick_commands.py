#  Copyright (c) 2026 Diego.
#
#  SPDX-License-Identifier: GPL-3.0-or-later
#
#  This file is part of arlo.
"""Validated quick-command groups backed by the user's commands.json."""

from __future__ import annotations

import json
from pathlib import Path

from .config import HOME_PATH


COMMANDS_FILE = HOME_PATH / "json" / "commands.json"


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
