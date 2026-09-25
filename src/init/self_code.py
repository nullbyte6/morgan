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

from src.init.lang import tr
from .identity import get_assistant


import ast
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
INSPECTION_CONTEXT_CHARACTERS = 32000
SEARCH_CODE_MAX_RESULTS = 20


@dataclass
class InspectionContextBudget:
    remaining: int = INSPECTION_CONTEXT_CHARACTERS


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


INSPECTION_BUDGET_EXHAUSTED = (
    "INSPECTION_BUDGET_EXHAUSTED: No inspection context remains for this turn. "
    "Do not retry read_code, search_code, or list_code with different ranges, "
    "offsets, paths, or queries to obtain more source. Use the source evidence "
    "already collected. If required evidence is still missing, state that it "
    "could not be verified."
)


def _inspection_budget_exhausted() -> bool:
    budget = _inspection_budget.get()
    return budget is not None and budget.remaining <= 0

def _claim_inspection_characters(requested: int) -> int:
    budget = _inspection_budget.get()
    if budget is None:
        return min(requested, READ_CODE_MAX_CHARACTERS)
    claimed = min(requested, READ_CODE_MAX_CHARACTERS, budget.remaining)
    budget.remaining -= claimed
    return claimed


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
    """List source entries with bounded pagination within the per-turn inspection budget.
    If INSPECTION_BUDGET_EXHAUSTED is returned, do not retry source-inspection tools
    with different arguments; continue from existing evidence.
    """
    from .brain import list_files
    if _inspection_budget_exhausted():
        return INSPECTION_BUDGET_EXHAUSTED
    try:
        if offset < 0 or limit < 1:
            raise ValueError("offset must be non-negative and limit must be positive")
        result = list_files(str(_path(directory)), recursive=recursive,
                            suffix=suffix)
        entries = result.splitlines()
        bounded_limit = min(limit, LIST_CODE_MAX_ENTRIES)
        requested = "\n".join(entries[offset:offset + bounded_limit])
        allowance = _claim_inspection_characters(len(requested))
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
            return INSPECTION_BUDGET_EXHAUSTED
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
    not conversation history or long-term memory. Inspection context is finite
    for each turn. If INSPECTION_BUDGET_EXHAUSTED is returned, do not retry
    source-inspection tools with different arguments; continue from existing
    evidence and mark anything still unverified explicitly.
    """
    if _inspection_budget_exhausted():
        return INSPECTION_BUDGET_EXHAUSTED
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
                f"No source matches found for {query!r}. "
                "Search is plain text, not regex. Try a concrete symbol, "
                "identifier, or a few relevant terms.")

        output = "\n".join(matches)
        allowance = _claim_inspection_characters(len(output))

        if allowance == 0:
            return INSPECTION_BUDGET_EXHAUSTED

        if allowance < len(output):
            output = output[:allowance]
            output += (
                "\nResults truncated by the remaining inspection context budget. "
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
    """Inspect a bounded source range within the per-turn inspection budget.
    Use search_code() first to locate relevant symbols and request only the
    necessary ranges. Inspection context is finite for each turn. If the tool
    reports INSPECTION_BUDGET_EXHAUSTED, do not retry source-inspection tools
    with other ranges or queries; continue from existing evidence and mark
    anything still unverified explicitly.
    """
    from .brain import read_file
    if _inspection_budget_exhausted():
        return INSPECTION_BUDGET_EXHAUSTED
    try:
        if start_line < 1 or end_line < 0 or character_offset < 0:
            raise ValueError("line numbers and character_offset cannot be negative")
        if end_line and end_line < start_line:
            raise ValueError("end_line cannot be before start_line")
        result = read_file(str(_path(path)))
        lines = result.splitlines(keepends=True)
        total_lines = len(lines)
        if (start_line == 1 and not end_line and character_offset == 0
                and len(result) > READ_CODE_MAX_CHARACTERS):
            index = _source_index(path, result)
            allowance = _claim_inspection_characters(len(index))
            if allowance == 0:
                return INSPECTION_BUDGET_EXHAUSTED
            output = index[:allowance]
            if allowance < len(index):
                output += "\nIndex truncated by the remaining inspection context budget."
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
        allowance = _claim_inspection_characters(
            max(0, len(block) - character_offset))
        if allowance == 0:
            return INSPECTION_BUDGET_EXHAUSTED
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
            if _inspection_budget_exhausted():
                header += (
                    " Inspection context budget exhausted after this partial range. "
                    "Do not request another source range this turn.")
            else:
                header += (
                    " Continue this range with read_code(path="
                    f"{path!r}, start_line={start_line}, end_line={bounded_end}, "
                    f"character_offset={next_character})."
                )
        elif bounded_end < total_lines:
            if _inspection_budget_exhausted():
                header += (
                    " Inspection context budget exhausted after this range. "
                    "Do not request another source range this turn.")
            else:
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

        if not old_text or content.count(old_text) != 1:
            failures = _record_edit_failure(path, old_text)

            if failures >= MAX_EQUIVALENT_EDIT_FAILURES:
                return (
                    "EDIT_RETRY_BLOCKED: This equivalent edit has already failed "
                    f"{failures} times for {path!r}. Do not retry this edit or make "
                    "cosmetic variations of old_text. Use the source evidence already "
                    "collected and either choose a genuinely different implementation "
                    "strategy or stop and report the blocker.")

            return (
                "EDIT_FAILED: old_text must match exactly once. "
                "Re-read only the smallest necessary source range before retrying. "
                "Do not retry the same old_text unchanged.")

        updated = content.replace(old_text, new_text, 1)

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
                f"{path!r} have failed {failures} times. Stop retrying this operation "
                f"and report the blocker. Last error: {error}")

        return tr(
            'self_code.error_editing_code',
            value0=get_assistant().name,
            error=error)


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
