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


import json
import logging
import subprocess
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from src.init.visuals.browser_bridge import open_embedded_url
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
READ_CODE_MAX_CHARACTERS = 3000
READ_CODE_MAX_LINES = 160
LIST_CODE_MAX_ENTRIES = 200
INSPECTION_CONTEXT_CHARACTERS = 24000


@dataclass
class InspectionContextBudget:
    remaining: int = INSPECTION_CONTEXT_CHARACTERS


_inspection_budget = ContextVar("inspection_context_budget", default=None)


@contextmanager
def inspection_context_scope():
    token = _inspection_budget.set(InspectionContextBudget())
    try:
        yield
    finally:
        _inspection_budget.reset(token)


def _claim_inspection_characters(requested: int) -> int:
    budget = _inspection_budget.get()
    if budget is None:
        return min(requested, READ_CODE_MAX_CHARACTERS)
    claimed = min(requested, READ_CODE_MAX_CHARACTERS, budget.remaining)
    budget.remaining -= claimed
    return claimed


def _path(path):
    target = (ROOT / path).resolve()
    relative = target.relative_to(ROOT)
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
        {"repository": str(ROOT), "entrypoint": str(ROOT / "entry" / "desktop.py"),
         "user_config": str(CONFIG_FILE), "git_status": git_status(str(ROOT))},
        ensure_ascii=False)


def list_code(directory: str = ".", recursive: bool = False,
              suffix: str = "", offset: int = 0,
              limit: int = LIST_CODE_MAX_ENTRIES) -> str:
    """List source entries with bounded pagination; offset selects the first entry."""
    from .brain import list_files
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
            header += " Inspection context budget exhausted for this turn."
        if end < len(entries):
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


def read_code(path: str, start_line: int = 1, end_line: int = 0,
              character_offset: int = 0) -> str:
    """Read a bounded source range; use line bounds and character_offset to continue."""
    from .brain import read_file
    try:
        if start_line < 1 or end_line < 0 or character_offset < 0:
            raise ValueError("line numbers and character_offset cannot be negative")
        if end_line and end_line < start_line:
            raise ValueError("end_line cannot be before start_line")
        result = read_file(str(_path(path)))
        lines = result.splitlines(keepends=True)
        total_lines = len(lines)
        if start_line > max(total_lines, 1):
            raise ValueError(f"start_line exceeds the file's {total_lines} lines")
        requested_end = end_line or min(total_lines, start_line + READ_CODE_MAX_LINES - 1)
        bounded_end = min(requested_end, total_lines,
                          start_line + READ_CODE_MAX_LINES - 1)
        block = "".join(lines[start_line - 1:bounded_end])
        allowance = _claim_inspection_characters(
            max(0, len(block) - character_offset))
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
        if not chunk:
            header += " Inspection context budget exhausted for this turn."
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
    """Replace one exact source fragment after reading it. Preserves encoding.
    Refuses ambiguous matches and invalid Python syntax. Changes are saved on
    disk; restart the assistant to activate them reliably. Does not commit or push.
    """
    from .brain import atomic_write_bytes, decode_text
    try:
        target = _path(path)
        content, encoding = decode_text(target.read_bytes())
        if not old_text or content.count(old_text) != 1:
            return tr('self_code.error_old_text_must_match_exactly_once_read_the_file_and_use_a_u')
        updated = content.replace(old_text, new_text, 1)
        if target.suffix.lower() == ".py":
            compile(updated, str(target), "exec")
        atomic_write_bytes(target, updated.encode(encoding))
        return tr('self_code.updated_restart_to_activate_the_change_no_commit_or_push_perform', target=target, value1=get_assistant().name)
    except (OSError, ValueError, UnicodeError, SyntaxError) as error:
        return tr('self_code.error_editing_code', value0=get_assistant().name, error=error)


def update_repo() -> str:
    """Pull the assistant's configured upstream with fast-forward only, when requested.
    Refuses local changes, including untracked files. Does not restart the assistant,
    install dependencies, change version settings, commit, or push.
    """
    from .brain import run_git
    try:
        status = subprocess.run(
            ["git", "-C", str(ROOT), "status", "--porcelain",
             "--untracked-files=all"],
            capture_output=True, text=True, errors="replace", timeout=15,
        )
        if status.returncode:
            return tr('self_code.error_checking_repository', value0=get_assistant().name, value1=status.stderr.strip())
        if status.stdout.strip():
            return tr('self_code.error_has_local_changes_resolve_them_before_updating', value0=get_assistant().name) + status.stdout.strip()
        result = run_git(str(ROOT), ["pull", "--ff-only"])
        return result + tr('self_code.only_files_on_disk_were_updated_if_git_succeeded_restart_to_load', value0=get_assistant().name)
    except (OSError, subprocess.TimeoutExpired) as error:
        return tr('self_code.error_updating_repository', value0=get_assistant().name, error=error)
