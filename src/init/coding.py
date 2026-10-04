#  Copyright (c) 2026 Diego.
#
#  SPDX-License-Identifier: GPL-3.0-or-later
#
#  This file is part of morgan.
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
from __future__ import annotations
from src.init.identity import get_assistant_name

import asyncio

from pydantic_ai import Agent, Tool, UsageLimits
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.providers.ollama import OllamaProvider

CODING_TOOLS = (
    "get_working_directory", "list_files", "read_file", "create_file", "edit_file",
    "append_file", "replace_in_file", "execute_command", "git_status", "git_diff")
CODING_REQUEST_LIMIT = 40


def coding_instructions() -> str:
    return (
        f"You are {get_assistant_name()}'s coding module. Complete the coding task with the "
        "available tools: inspect the relevant files first, make the changes, then run the "
        "project's own checks or the script itself to verify them. Make only the changes the "
        "task requires and never delete files. Continue after recoverable errors and stop only "
        "when the task is complete or blocked by essential missing details. Finish with a short "
        "report, in the language of the task, of the files changed and the verification result, "
        "without pasting whole files.")


def coding_tools() -> list[Tool]:
    from src.init.tools import TOOLS

    return [Tool(function, sequential=True) for function in TOOLS
            if function.__name__ in CODING_TOOLS]


async def delegate_coding_async(task: str) -> str:
    """Run a coding task with the separate coding model and return its report."""
    from src.init.brain import get_coding_model

    provider = OllamaProvider(base_url="http://localhost:11434/v1")
    agent = Agent(
        OllamaModel(
            get_coding_model(), provider=provider,
            profile={"openai_chat_supports_multiple_system_messages": False,
                     "openai_chat_supports_max_completion_tokens": False,
                     "openai_supports_tool_choice_required": False},
            settings={"thinking": False, "openai_reasoning_effort": "none",
                      "temperature": 0.2}),
        instructions=coding_instructions(), tools=coding_tools())
    try:
        result = await agent.run(
            task, usage_limits=UsageLimits(request_limit=CODING_REQUEST_LIMIT))
    finally:
        await provider.client.close()
    return result.output


def delegate_coding(task: str) -> str:
    """Hand a real coding job to the dedicated coding model and return its report.

    Use this to write, modify, debug or review code in actual project or script files,
    and to run the project's checks. Do not use it to explain code, show examples in the
    chat, or run a simple command; handle those yourself. Change to the project's
    directory first when the job is about a specific project.
    Args:
        task: A complete, self-contained description of the coding job, including the
            relevant paths, the expected behavior and any constraints.
    Returns:
        The coding model's report of what it changed and how it verified the result.
    """
    return asyncio.run(delegate_coding_async(task))
