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
"""Access the assistant's own checkout independently of the user's working directory."""

from PIL.PdfParser import decode_text

from requests.packages import target

from src.init.lang import tr
from .identity import get_assistant


import ast
import hashlib
import json
import logging
import subprocess
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from src.init.visuals.browser_bridge import open_embedded_url
from src.init.paths import ARLO_ROOT

READ_CODE_MAX_CHARACTERS = 3000
READ_CODE_MAX_LINES = 160
LIST_CODE_MAX_ENTRIES = 200
INSPECTION_CONTEXT_CHARACTERS = 20000
SEARCH_CODE_MAX_RESULTS = 20
INSPECTION_TOOLS = frozenset(("read_code", "search_code", "list_code"))


@dataclass
class InspectionContextBudget:
    resident_characters: int = 0

    def compact(self, messages, archive, preview_characters=0):
        self.resident_characters = preview_characters
        retained = {}
        archived = []
        reused = []
        source_characters = 0
        arguments = {}
        for message in messages:
            for part in message.parts:
                if part.part_kind == "tool-call" and part.tool_name in INSPECTION_TOOLS:
                    try:
                        arguments[part.tool_call_id] = part.args_as_dict()
                    except (ValueError, TypeError, AssertionError):
                        arguments[part.tool_call_id] = {}
        for message in reversed(messages):
            for part in reversed(message.parts):
                if (part.part_kind != "tool-return" or part.tool_name not in INSPECTION_TOOLS
                        or not isinstance(part.content, str)):
                    continue
                content = part.content
                if content.startswith(("Archived source evidence:", "Source evidence reused from")):
                    continue
                source_characters += len(content)
                payload = (content.split("\n\n", 1)[-1]
                           if content.startswith(("Source:", "Source listing:")) else content)
                args = arguments.get(part.tool_call_id, {})
                location = args.get("path", args.get("directory", "."))
                try:
                    location = str(_path(location)).casefold()
                except (OSError, ValueError):
                    location = str(location)
                key = (part.tool_name, location, hashlib.sha256(payload.encode("utf-8")).hexdigest())
                if key in retained:
                    part.content = f"Source evidence reused from tool call {retained[key]}."
                    reused.append(part.tool_call_id)
                elif self.resident_characters + len(content) <= INSPECTION_CONTEXT_CHARACTERS:
                    retained[key] = part.tool_call_id
                    self.resident_characters += len(content)
                else:
                    part.content = "Archived source evidence: " + archive(
                        json.dumps(content, ensure_ascii=False), f"Source evidence {part.tool_call_id}")
                    archived.append(part.tool_call_id)
        return {"limit": INSPECTION_CONTEXT_CHARACTERS,
                "source_characters_before": source_characters,
                "resident_characters": self.resident_characters,
                "preview_characters": preview_characters,
                "retained": list(retained.values()), "archived": archived, "reused": reused}


_inspection_budget = ContextVar("inspection_context_budget", default=None)

@dataclass
class EditAttemptState:
    failures: dict[tuple[str, str], int]


_edit_attempt_state = ContextVar("edit_attempt_state", default=None)
MAX_EQUIVALENT_EDIT_FAILURES = 2

@contextmanager
def inspection_context_scope():
    budget_token = _inspection_budget.set(InspectionContextBudget())
    edit_token = _edit_attempt_state.set(EditAttemptState(failures={}))
    try:
        yield
    finally:
        _edit_attempt_state.reset(edit_token)
        _inspection_budget.reset(budget_token)

def _edit_failure_key(path: str, old_text: str) -> tuple[str, str]:
    import hashlib

    digest = hashlib.sha256(
        old_text.encode("utf-8", errors="replace")
    ).hexdigest()

    return path.casefold(), digest


def _record_edit_failure(path: str, old_text: str) -> int:
    state = _edit_attempt_state.get()

    if state is None:
        return 1

    key = _edit_failure_key(path, old_text)
    failures = state.failures.get(key, 0) + 1
    state.failures[key] = failures
    return failures


def _clear_edit_failures(path: str) -> None:
    state = _edit_attempt_state.get()

    if state is None:
        return

    normalized = path.casefold()

    for key in tuple(state.failures):
        if key[0] == normalized:
            del state.failures[key]


def compact_inspection_context(messages, archive, preview_characters=0):
    budget = _inspection_budget.get()
    if budget is None:
        budget = InspectionContextBudget()
    return budget.compact(messages, archive, preview_characters)


def _inspection_allowance(requested: int) -> int:
    return min(requested, READ_CODE_MAX_CHARACTERS)


def _source_index(path: str, content: str) -> str:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return ""
    entries = []

    def visit(body, prefix=""):
        for node in body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                name = f"{prefix}{node.name}"
                entries.append(
                    f"{kind} {name}: lines {node.lineno}-{getattr(node, 'end_lineno', node.lineno)}")
                visit(node.body, name + ".")

    visit(tree.body)
    return f"Source index: {path}\n" + "\n".join(entries)


def _path(path):
    target = (ARLO_ROOT / path).resolve()
    relative = target.relative_to(ARLO_ROOT)
    if any(part in (".git", ".venv", "__pycache__") for part in relative.parts):
        raise ValueError(
            tr('self_code.choose_a_source_file_not_git_metadata_or_the_runtime'))
    return target


def get_repo_lnk() -> str:
    """Open the assistant's public repository in Arlo's integrated browser.
    Use when asked to open the assistant's online repository, not to inspect local code.
    """
    url = "https://github.com/xddigs/arlo"
    try:
        open_embedded_url(url)
        return tr('self_code.opened_repository_in_the_default_browser', url=url)
    except Exception as error:
        return tr('self_code.error_opening_repository_repository', error=error, url=url)


def get_repo() -> str:
    """Locate the assistant's actual source checkout and report its Git status."""
    from .brain import git_status
    from .config import CONFIG_FILE
    return json.dumps(
        {
            "repository": str(ARLO_ROOT),
            "entrypoint": str(ARLO_ROOT / "entry" / "desktop.py"),
            "user_config": str(CONFIG_FILE),
            "git_status": git_status(str(ARLO_ROOT)),
        },
        ensure_ascii=False)


def list_code(directory: str = ".", recursive: bool = False,
              suffix: str = "", offset: int = 0,
              limit: int = LIST_CODE_MAX_ENTRIES) -> str:
    """List source entries with bounded pagination in the working inspection context.
    Reuse existing evidence. Older results may be archived to make room for new evidence.
    """
    from .brain import list_files
    try:
        if offset < 0 or limit < 1:
            raise ValueError("offset must be non-negative and limit must be positive")
        result = list_files(str(_path(directory)), recursive=recursive,
                            suffix=suffix)
        entries = result.splitlines()
        bounded_limit = min(limit, LIST_CODE_MAX_ENTRIES)
        requested = "\n".join(entries[offset:offset + bounded_limit])
        allowance = _inspection_allowance(len(requested))
        if (offset == 0 and len(entries) <= bounded_limit
                and allowance == len(result)):
            return result
        selected = []
        selected_characters = 0
        for entry in entries[offset:offset + bounded_limit]:
            added = len(entry) + int(bool(selected))
            if selected_characters + added > allowance:
                break
            selected.append(entry)
            selected_characters += added
        end = offset + len(selected)
        header = (f"Source listing: {directory}; entries {offset + 1}-{end} "
                  f"of {len(entries)}.")
        if not selected:
            return f"No source entries at offset {offset}."
        elif end < len(entries):
            header += (" Continue with list_code(directory="
                       f"{directory!r}, recursive={recursive!r}, suffix={suffix!r}, "
                       f"offset={end}, limit={bounded_limit}).")
        output = header + "\n\n" + "\n".join(selected)
        logging.getLogger("arlo.context").info(
            "Bounded list_code source=%s entries=%d returned=%d offset=%d bytes=%d",
            directory, len(entries), len(selected), offset,
            len(output.encode("utf-8")))
        return output
    except (OSError, ValueError) as error:
        return f"Error: {error}"


def search_code(query: str, directory: str = ".",
                suffix: str = ".py",
                limit: int = SEARCH_CODE_MAX_RESULTS) -> str:
    """Search Arlo's local source checkout for text or symbols.
    Plain-text search only; regular expressions are not supported.
    An exact phrase match is preferred. If the complete query does not occur
    literally, multiple whitespace-separated terms are matched when all of
    them occur on the same source line, regardless of order or text between
    them.
    Returns bounded matching paths, line numbers and source lines. Use this
    to locate relevant source before read_code(). This searches source files,
    not conversation history or long-term memory. Reuse existing evidence;
    older results may be archived to make room for new evidence. Avoid repeating
    equivalent searches without new information.
    """
    try:
        query = query.strip()
        if not query:
            raise ValueError("query cannot be empty")
        if limit < 1 or limit > SEARCH_CODE_MAX_RESULTS:
            raise ValueError(
                f"limit must be between 1 and {SEARCH_CODE_MAX_RESULTS}")

        root = _path(directory)
        if not root.is_dir():
            raise ValueError("directory must be a directory")

        needle = query.casefold()
        terms = tuple(
            dict.fromkeys(
                term for term in needle.split()
                if term))

        exact_matches = []
        term_matches = []

        files = sorted(
            path for path in root.rglob(f"*{suffix}")
            if path.is_file()
            and ".git" not in path.parts
            and ".venv" not in path.parts
            and "__pycache__" not in path.parts)

        for path in files:
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue

            relative = path.relative_to(ARLO_ROOT)
            for line_number, line in enumerate(content.splitlines(), start=1):
                folded = line.casefold()

                if needle in folded:
                    exact_matches.append(
                        f"{relative}:{line_number}: {line.strip()}")
                    continue

                if len(terms) > 1 and all(term in folded for term in terms):
                    term_matches.append(
                        f"{relative}:{line_number}: {line.strip()}")

        matches = (exact_matches + term_matches)[:limit]
        if not matches:
            logging.getLogger("arlo.context").info(
                "search_code query=%r directory=%s "
                "exact_matches=0 term_matches=0 returned_bytes=0",
                query,
                directory)
            return (
                "No source matches found. "
                "Search is plain text, not regex. Try a concrete symbol, "
                "identifier, or a few relevant terms.")

        output = "\n".join(matches)
        allowance = _inspection_allowance(len(output))

        if allowance < len(output):
            output = output[:allowance]
            output += (
                "\nResults truncated by the per-call inspection limit. "
                "Use the returned matches selectively.")

        logging.getLogger("arlo.context").info(
            "search_code query=%r directory=%s "
            "exact_matches=%d term_matches=%d returned_matches=%d "
            "returned_bytes=%d",
            query,
            directory,
            len(exact_matches),
            len(term_matches),
            len(matches),
            len(output.encode("utf-8")))

        return output

    except (OSError, ValueError) as error:
        return f"Error searching source code: {error}"


def read_code(path: str, start_line: int = 1, end_line: int = 0,
              character_offset: int = 0) -> str:
    """Inspect a bounded source range in the working inspection context.
    Use search_code() first to locate relevant symbols and request only the
    necessary ranges. Reuse existing evidence; older results may be archived
    to make room for new evidence. Do not repeatedly read unchanged ranges.
    """
    from .brain import decode_text

    try:
        if start_line < 1 or end_line < 0 or character_offset < 0:
            raise ValueError("line numbers and character_offset cannot be negative")
        if end_line and end_line < start_line:
            raise ValueError("end_line cannot be before start_line")
        target = _path(path)
        result, _ = decode_text(target.read_bytes())
        lines = result.splitlines(keepends=True)
        total_lines = len(lines)
        if (start_line == 1 and not end_line and character_offset == 0
                and len(result) > READ_CODE_MAX_CHARACTERS):
            index = _source_index(path, result)
            output = (index or result)[:READ_CODE_MAX_CHARACTERS]
            allowance = len(output)
            if allowance < len(index):
                output += "\nIndex truncated by the per-call inspection limit."
            logging.getLogger("arlo.context").info(
                "Indexed read_code source=%s total_lines=%d total_bytes=%d "
                "returned_bytes=%d",
                path, total_lines, len(result.encode("utf-8")),
                len(output.encode("utf-8")))
            return output
        if start_line > max(total_lines, 1):
            raise ValueError(f"start_line exceeds the file's {total_lines} lines")
        requested_end = end_line or min(total_lines, start_line + READ_CODE_MAX_LINES - 1)
        bounded_end = min(requested_end, total_lines,
                          start_line + READ_CODE_MAX_LINES - 1)
        block = "".join(lines[start_line - 1:bounded_end])
        allowance = _inspection_allowance(
            max(0, len(block) - character_offset))
        if allowance == 0:
            return f"No source characters at offset {character_offset} in this range."
        if (start_line == 1 and not end_line and character_offset == 0
                and len(result) <= READ_CODE_MAX_CHARACTERS
                and allowance == len(result)):
            return result
        chunk = block[character_offset:character_offset + allowance]
        next_character = character_offset + len(chunk)
        header = (
            f"Source: {path}; lines {start_line}-{bounded_end} of {total_lines}; "
            f"characters {character_offset}-{next_character} of {len(block)} in this range; "
            f"file characters={len(result)}."
        )
        if next_character < len(block):
            header += (
                " Continue this range with read_code(path="
                f"{path!r}, start_line={start_line}, end_line={bounded_end}, "
                f"character_offset={next_character})."
            )
        elif bounded_end < total_lines:
            header += f" Continue with read_code(path={path!r}, start_line={bounded_end + 1})."
        output = header + "\n\n" + chunk
        logging.getLogger("arlo.context").info(
            "Bounded read_code source=%s total_lines=%d total_bytes=%d "
            "range=%d-%d offset=%d returned_bytes=%d",
            path, total_lines, len(result.encode("utf-8")), start_line,
            bounded_end, character_offset, len(output.encode("utf-8")))
        return output
    except (OSError, ValueError) as error:
        return f"Error: {error}"


def edit_code(path: str, old_text: str, new_text: str) -> str:
    """Replace one exact fragment in Arlo's own source code.
    Use this tool exclusively when modifying Arlo's own repository.
    Do not use edit_file or replace_in_file for Arlo source changes.
    Args:
        path: Source path relative to Arlo's repository root.
        old_text: Exact existing source fragment to replace.
        new_text: Replacement source fragment.
    """
    from .brain import atomic_write_bytes, decode_text

    try:
        target = _path(path)
        content, encoding = decode_text(target.read_bytes())
        normalized_content = content.replace("\r\n", "\n").replace("\r", "\n")
        normalized_old_text = old_text.replace("\r\n", "\n").replace("\r", "\n")

        matches = normalized_content.count(normalized_old_text) if normalized_old_text else 0
        if matches != 1:
            failures = _record_edit_failure(path, old_text)

            if failures >= MAX_EQUIVALENT_EDIT_FAILURES:
                return (
                    "EDIT_RETRY_BLOCKED: This equivalent edit has already failed "
                    f"{failures} times for {path!r}. "
                    f"old_text matched {matches} times; exactly one match is required. "
                    "Do not retry this edit or make cosmetic variations of old_text. "
                    "Use the source evidence already collected and either choose a "
                    "genuinely different implementation strategy or stop and report "
                    "the blocker.")

            return (
                f"EDIT_FAILED: old_text matched {matches} times; "
                "exactly one match is required. "
                "Re-read only the smallest necessary source range before retrying. "
                "Do not retry the same old_text unchanged.")

        start = normalized_content.index(normalized_old_text)
        end = start + len(normalized_old_text)
    
        normalized_new_text = new_text.replace("\r\n", "\n").replace("\r", "\n")
        normalized_updated = (normalized_content[:start] + normalized_new_text + normalized_content[end:])

        newline = "\r\n" if "\r\n" in content else "\n"

        if newline == "\r\n":
            updated = normalized_updated.replace("\n", "\r\n")
        else:
            updated = normalized_updated

        if target.suffix.lower() == ".py":
            compile(updated, str(target), "exec")

        atomic_write_bytes(target, updated.encode(encoding))
        _clear_edit_failures(path)

        return tr(
            'self_code.updated_restart_to_activate_the_change_no_commit_or_push_perform',
            target=target,
            value1=get_assistant().name)

    except (OSError, ValueError, UnicodeError, SyntaxError) as error:
        failures = _record_edit_failure(path, old_text)

        if failures >= MAX_EQUIVALENT_EDIT_FAILURES:
            return (
                "EDIT_RETRY_BLOCKED: Equivalent edits for "
                f"{path!r} have failed {failures} times. "
                "Stop retrying this operation and report the blocker. "
                f"Last error: {error}"
            )

        return tr(
            'self_code.error_editing_code',
            value0=get_assistant().name,
            error=error
        )


def update_repo() -> str:
    """Pull the assistant's configured upstream with fast-forward only, when requested.
    Refuses local changes, including untracked files. Does not restart the assistant,
    install dependencies, change version settings, commit, or push.
    """
    from .brain import run_git
    try:
        status = subprocess.run(
            ["git", "-C", str(ARLO_ROOT), "status", "--porcelain",
             "--untracked-files=all"],
            capture_output=True, text=True, errors="replace", timeout=15,
        )
        if status.returncode:
            return tr('self_code.error_checking_repository', value0=get_assistant().name, value1=status.stderr.strip())
        if status.stdout.strip():
            return tr('self_code.error_has_local_changes_resolve_them_before_updating', value0=get_assistant().name) + status.stdout.strip()
        result = run_git(str(ARLO_ROOT), ["pull", "--ff-only"])
        return result + tr('self_code.only_files_on_disk_were_updated_if_git_succeeded_restart_to_load', value0=get_assistant().name)
    except (OSError, subprocess.TimeoutExpired) as error:
        return tr('self_code.error_updating_repository', value0=get_assistant().name, error=error)


def get_repo_state() -> str:
    """Return a deterministic snapshot of Arlo's current Git working tree."""
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(ARLO_ROOT),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=15,
        )
        if result.returncode:
            return ""
        return result.stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""
