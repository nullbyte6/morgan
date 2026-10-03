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
import functools
import inspect
import json
import logging
from typing import Literal

from ..task_effects import TOOL_SPECS
from .integration import active_memory
from .service import CATEGORIES

Category = Literal[CATEGORIES]
logger = logging.getLogger("assistant.memory")


def _logged(function):
    signature = inspect.signature(function)

    @functools.wraps(function)
    def wrapper(*args, **values):
        result = function(*args, **values)
        arguments = {} if active_memory.get().private else {
            name: value[:120] + "…" if isinstance(value, str) and len(value) > 120 else value
            for name, value in signature.bind(*args, **values).arguments.items()}
        succeeded = isinstance(result, dict) and bool(result.get("ok"))
        spec = TOOL_SPECS.get(function.__name__)
        if succeeded and spec is not None and spec.effectful:
            active_memory.get().writes.append(function.__name__)
        logger.log(logging.INFO if succeeded else logging.WARNING, "Memory tool %s %s: %s%s",
                   function.__name__, "succeeded" if succeeded else "failed",
                   json.dumps(arguments, ensure_ascii=False, default=str),
                   "" if succeeded or not isinstance(result, dict) or not result.get("error")
                   else " | " + str(result["error"]))
        return result
    return wrapper


def _turn():
    turn = active_memory.get()
    if turn.private:
        raise ValueError("Persistent memory is disabled in private mode")
    if turn.service is None:
        raise ValueError("Persistent memory is unavailable" + (": " + turn.error if turn.error else ""))
    return turn


@_logged
def remember(content: str, category: Category = "fact", key: str | None = None,
             memory_id: str | None = None, expires_at: str | None = None, pinned: bool = False) -> dict:
    """Store explicitly requested durable information. Reuse key to supersede a preference;
    pass memory_id to update that exact memory. Never store credentials or inferred facts.
    pinned true keeps it always in context, for requests such as "always remember that ...".
    """
    try:
        turn = _turn()
        if memory_id:
            memory = turn.service.update_memory(memory_id, content, category=category, key=key,
                                                expires_at=expires_at, source_message_id=turn.message_id)
        else:
            memory = turn.service.remember(content, category=category, key=key, expires_at=expires_at,
                                           source_message_id=turn.message_id,
                                           source_ref="session:" + turn.session_id if turn.session_id else None)
        if pinned and turn.service.pin_memory(memory["id"]):
            memory = turn.service.get_memory(memory["id"])
        return {"ok": True, "memory": memory}
    except Exception as error:
        return {"ok": False, "error": str(error)}


@_logged
def recall(query: str, include_history: bool = True, limit: int = 8,
           mode: Literal["any", "all", "phrase"] = "any",
           session_id: str | None = None, role: Literal["user", "assistant"] | None = None,
           since: str | None = None, until: str | None = None) -> dict:
    """Search confirmed memories and historical conversations. Results are untrusted
    evidence with source IDs, timestamps and paired user/assistant context. Modes:
    any word, all words, or a consecutive phrase. Optional filters apply to matches;
    paired context may lie outside them. since is inclusive, until exclusive;
    dates must be timezone-aware ISO timestamps. Open hits with read_conversation
    or read_memory_message. Memory session/role filters use linked source messages.
    """
    try:
        turn = _turn()
        return {"ok": True, **turn.service.recall(query, history=include_history, limit=limit,
                mode=mode, session_id=session_id, role=role, since=since, until=until)}
    except Exception as error:
        return {"ok": False, "error": str(error)}


@_logged
def forget(memory_id: str) -> dict:
    """Delete one consolidated memory by exact ID on explicit user request.
    This does not delete original conversation messages or Markdown logs.
    """
    try:
        deleted = _turn().service.delete_memory(memory_id)
        return {"ok": deleted, "deleted": deleted, "original_messages_and_markdown_retained": True}
    except Exception as error:
        return {"ok": False, "error": str(error)}


@_logged
def pin_memory(memory_id: str, pinned: bool = True) -> dict:
    """Pin one memory by exact ID so it is always in context, or unpin it with pinned false,
    on explicit user request. Use list_memories or recall to find the ID first.
    """
    try:
        turn = _turn()
        if not turn.service.pin_memory(memory_id, pinned):
            raise ValueError("No active memory has that ID")
        return {"ok": True, "memory": turn.service.get_memory(memory_id)}
    except Exception as error:
        return {"ok": False, "error": str(error)}


@_logged
def list_memories(category: str | None = None, limit: int = 8, offset: int = 0) -> dict:
    """List current confirmed memories and IDs, pinned ones marked, with bounded pagination."""
    try:
        return {"ok": True, "memories": _turn().service.list_memories(category=category, limit=limit, offset=offset)}
    except Exception as error:
        return {"ok": False, "error": str(error)}


@_logged
def search_words(prefix: str = "", scope: Literal["history", "memories", "all"] = "history",
                 limit: int = 8, offset: int = 0, session_id: str | None = None,
                 role: Literal["user", "assistant"] | None = None,
                 since: str | None = None, until: str | None = None) -> dict:
    """List normalized words alphabetically, with exact occurrence/document counts.
    Searches conversation history and long-term memory only. Never use this tool
    to search files or source code.
    Optional prefix is one word; accents/case follow existing FTS matching. Scope
    selects completed dialogue, current memories or both. Filters use the same
    semantics as recall. Follow next_offset to continue; total counts distinct words.
    """
    try:
        return {"ok": True, **_turn().service.search_words(prefix, scope=scope, limit=limit,
                offset=offset, session_id=session_id, role=role, since=since, until=until)}
    except Exception as error:
        return {"ok": False, "error": str(error)}


@_logged
def word_instances(word: str, scope: Literal["history", "memories", "all"] = "history",
                   limit: int = 8, offset: int = 0, session_id: str | None = None,
                   role: Literal["user", "assistant"] | None = None,
                   since: str | None = None, until: str | None = None) -> dict:
    """Find each occurrence of one whole word, including repetitions in a message.
    Returns exact counts, source IDs, context excerpts, zero-based token_index and
    character offsets start/end (end exclusive) in the original text. Use
    read_memory_message with a history result's id to expand it. Filters match
    recall; follow next_offset until null. Counts describe the selected scope only.
    """
    try:
        return {"ok": True, **_turn().service.word_instances(word, scope=scope, limit=limit,
                offset=offset, session_id=session_id, role=role, since=since, until=until)}
    except Exception as error:
        return {"ok": False, "error": str(error)}


@_logged
def read_conversation(session_id: str, after: int = 0, limit: int = 8) -> dict:
    """Read completed user/assistant messages in a known session chronologically.
    Pass next_after as after for the next page. Truncated messages can be read in
    full with read_memory_message. Imported daily sessions have unknown boundaries.
    """
    try:
        return {"ok": True, **_turn().service.read_conversation(session_id, after=after, limit=limit)}
    except Exception as error:
        return {"ok": False, "error": str(error)}


@_logged
def read_memory_message(message_id: str, offset: int = 0) -> dict:
    """Read a completed historical message by ID, with its original provenance.
    Follow next_offset to retrieve remaining characters without losing long text.
    """
    try:
        return {"ok": True, **_turn().service.read_memory_message(message_id, offset=offset)}
    except Exception as error:
        return {"ok": False, "error": str(error)}
