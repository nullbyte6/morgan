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


import ast
import base64
import hashlib
from typing import Annotated, Literal
import json
import logging
import subprocess
from pydantic import Field
from src.init.visuals.browser_bridge import open_embedded_url
from src.init.paths import PROJECT_ROOT
from .task_outcomes import ActionResult, Outcome, normalize_result

READ_CODE_MAX_CHARACTERS = 3000
READ_CODE_PAGE_CHARACTERS = 12000
READ_CODE_MAX_LINES = 320
LIST_CODE_MAX_ENTRIES = 200
SEARCH_CODE_MAX_RESULTS = 20


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
    target = (PROJECT_ROOT / path).resolve()
    relative = target.relative_to(PROJECT_ROOT)
    if any(part.casefold() in (".git", ".venv", "__pycache__") for part in relative.parts):
        raise ValueError(
            tr('self_code.choose_a_source_file_not_git_metadata_or_the_runtime'))
    return target


def get_repo_lnk() -> str:
    """Open the assistant's public repository in the assistant's integrated browser.
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
            "repository": str(PROJECT_ROOT),
            "entrypoint": str(PROJECT_ROOT / "entry" / "desktop.py"),
            "user_config": str(CONFIG_FILE),
            "git_status": git_status(str(PROJECT_ROOT)),
        },
        ensure_ascii=False)


def list_code(directory: str = ".", recursive: bool = False,
              suffix: str = "", offset: int = 0,
              limit: int = LIST_CODE_MAX_ENTRIES) -> dict:
    """List source entries with bounded pagination in the working inspection context.
    Reuse existing evidence. Older results may be archived to make room for new evidence.
    """
    from .brain import list_files
    try:
        if offset < 0 or limit < 1:
            raise ValueError("offset must be non-negative and limit must be positive")
        result = list_files(str(_path(directory)), recursive=recursive,
                            suffix=suffix)
        observation = normalize_result(result)
        if observation.outcome != Outcome.SUCCESS:
            return observation.payload()
        result = observation.data
        entries = result.splitlines()
        bounded_limit = min(limit, LIST_CODE_MAX_ENTRIES)
        requested = "\n".join(entries[offset:offset + bounded_limit])
        allowance = _inspection_allowance(len(requested))
        if (offset == 0 and len(entries) <= bounded_limit
                and allowance == len(result)):
            return ActionResult(Outcome.SUCCESS, result).payload()
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
            return ActionResult(Outcome.NEGATIVE, f"No source entries at offset {offset}.").payload()
        elif end < len(entries):
            header += (" Continue with list_code(directory="
                       f"{directory!r}, recursive={recursive!r}, suffix={suffix!r}, "
                       f"offset={end}, limit={bounded_limit}).")
        output = header + "\n\n" + "\n".join(selected)
        logging.getLogger("assistant.context").info(
            "Bounded list_code source=%s entries=%d returned=%d offset=%d bytes=%d",
            directory, len(entries), len(selected), offset,
            len(output.encode("utf-8")))
        return ActionResult(Outcome.SUCCESS, output).payload()
    except (OSError, ValueError) as error:
        return ActionResult(Outcome.REJECTED, str(error), "inspection_precondition").payload()


def search_code(query: str, directory: str = ".",
                suffix: str = ".py",
                limit: Annotated[int, Field(ge=1, le=SEARCH_CODE_MAX_RESULTS)] = SEARCH_CODE_MAX_RESULTS) -> dict:
    """Search the assistant's local source checkout for text or symbols.
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

            relative = path.relative_to(PROJECT_ROOT)
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
            logging.getLogger("assistant.context").info(
                "search_code query=%r directory=%s "
                "exact_matches=0 term_matches=0 returned_bytes=0",
                query,
                directory)
            return ActionResult(Outcome.NEGATIVE, {"matches": [], "query": query,
                                "repair": "Search a different single symbol or use list_code to discover actual source paths. Terms must all occur on the same line."}, "no_matches").payload()

        output = "\n".join(matches)
        allowance = _inspection_allowance(len(output))

        if allowance < len(output):
            output = output[:allowance]
            output += (
                "\nResults truncated by the per-call inspection limit. "
                "Use the returned matches selectively.")

        logging.getLogger("assistant.context").info(
            "search_code query=%r directory=%s "
            "exact_matches=%d term_matches=%d returned_matches=%d "
            "returned_bytes=%d",
            query,
            directory,
            len(exact_matches),
            len(term_matches),
            len(matches),
            len(output.encode("utf-8")))

        return ActionResult(Outcome.SUCCESS, output).payload()

    except (OSError, ValueError) as error:
        return ActionResult(Outcome.REJECTED, str(error), "inspection_precondition").payload()


def code_cursor(cursor):
    try:
        value = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
        if not isinstance(value, dict) or set(value) != {"version", "path", "revision", "mode", "start", "end", "offset"}:
            raise ValueError("Invalid cursor fields")
        if value["version"] != 1 or value["mode"] not in {"content", "index"} or not isinstance(value["path"], str):
            raise ValueError("Unsupported cursor")
        if not isinstance(value["revision"], str) or any(type(value[key]) is not int for key in ("start", "end", "offset")):
            raise ValueError("Invalid cursor types")
        if value["start"] < 1 or value["end"] < value["start"] or value["offset"] < 0:
            raise ValueError("Invalid cursor range")
        _path(value["path"])
        return value
    except (ValueError, TypeError, UnicodeError) as error:
        raise ValueError("Use an unchanged next_cursor returned by read_code") from error


def read_code(path: str = "", start_line: Annotated[int, Field(ge=1)] = 1,
              end_line: Annotated[int, Field(ge=0)] = 0,
              character_offset: Annotated[int, Field(ge=0)] = 0, cursor: str = "",
              mode: Literal["content", "index"] = "content") -> dict:
    """Read source content, or explicitly request mode='index'.
    Line numbers start at 1 and end_line is inclusive; 0 reads through the file's end.
    character_offset starts at 0 within the requested range.
    Results identify actual coverage, truncated and exhausted ranges, and next_cursor.
    Continue with read_code(cursor=next_cursor), without changing any range arguments.
    A cursor is bound to the source revision; stale cursors require restarting that range.
    Index pages describe symbols and never count as source-body coverage.
    """
    from .brain import decode_text
    def reject(field, expected, actual, reason):
        return ActionResult(Outcome.REJECTED, {"reason": reason, "field": field,
                            "expected": expected, "actual": actual, "recoverable": True},
                            "inspection_precondition").payload()
    try:
        continuation = code_cursor(cursor) if cursor else None
        if continuation:
            if ((path and _path(path) != _path(continuation["path"]))
                    or start_line not in (1, continuation["start"])
                    or end_line not in (0, continuation["end"])
                    or character_offset not in (0, continuation["offset"])
                    or mode not in ("content", continuation["mode"])):
                return reject("cursor", "An unchanged next_cursor without conflicting arguments", cursor,
                              "Cursor arguments conflict with the original path, range, offset or mode")
            path, start_line, end_line, character_offset, mode = (continuation[key]
                for key in ("path", "start", "end", "offset", "mode"))
        if not path:
            return reject("path", "A source path or returned cursor", path, "Supply a source path or returned cursor")
        for field, value, minimum in (("start_line", start_line, 1), ("end_line", end_line, 0),
                                       ("character_offset", character_offset, 0)):
            if value < minimum:
                return reject(field, {"minimum": minimum}, value, f"{field} must be at least {minimum}")
        if end_line and end_line < start_line:
            return reject("end_line", {"minimum": start_line, "through_file_end": 0}, end_line,
                          "end_line must be 0 or at least start_line")
        target = _path(path)
        raw = target.read_bytes()
        revision = hashlib.sha256(raw).hexdigest()
        if continuation and revision != continuation["revision"]:
            return ActionResult(Outcome.REJECTED, {"restart": {"path": path, "start_line": start_line,
                                "end_line": end_line, "mode": mode}}, "stale_cursor").payload()
        content, _ = decode_text(raw)
        lines = content.splitlines(keepends=True)
        total_lines = len(lines)
        if start_line > max(total_lines, 1):
            return reject("start_line", {"minimum": 1, "maximum": max(total_lines, 1)}, start_line,
                          f"start_line exceeds the file's {total_lines} lines")
        range_end = min(end_line or max(total_lines, 1), max(total_lines, 1))
        block = _source_index(path, content) if mode == "index" else "".join(lines[start_line - 1:range_end])
        if character_offset > len(block):
            return reject("character_offset", {"minimum": 0, "maximum": len(block)}, character_offset,
                          "Cursor/offset is beyond the requested range")
        page = block[character_offset:character_offset + READ_CODE_PAGE_CHARACTERS]
        page = "".join(page.splitlines(keepends=True)[:READ_CODE_MAX_LINES])
        next_offset = character_offset + len(page)
        truncated = next_offset < len(block)
        next_cursor = None
        if truncated:
            value = {"version": 1, "path": str(target), "revision": revision, "mode": mode,
                     "start": start_line, "end": range_end, "offset": next_offset}
            next_cursor = base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).decode()
        prefix = sum(len(line) for line in lines[:start_line - 1])
        data = {"resource": "file:" + str(target), "revision": revision, "kind": mode,
                "content": page, "truncated": truncated, "next_cursor": next_cursor,
                "exhausted": not truncated, "range": {"start_line": start_line, "end_line": range_end,
                    "character_offset": character_offset, "next_character_offset": next_offset},
                "coverage": {"kind": mode, "start_character": prefix + character_offset if mode == "content" else character_offset,
                    "end_character": prefix + next_offset if mode == "content" else next_offset},
                "total_lines": total_lines}
        return ActionResult(Outcome.SUCCESS if page else Outcome.NEGATIVE, data, "source_page").payload()
    except (OSError, ValueError) as error:
        return reject("cursor" if cursor else "path", "A source path or unchanged returned cursor",
                      cursor or path, str(error))


def edit_code(path: str, old_text: str, new_text: str) -> dict:
    """Replace exactly one existing fragment in assistant source, validating Python before atomic writes."""
    from .brain import atomic_write_bytes, decode_text
    try:
        target = _path(path)
        content, encoding = decode_text(target.read_bytes())
        normalized = content.replace("\r\n", "\n").replace("\r", "\n")
        old = old_text.replace("\r\n", "\n").replace("\r", "\n")
        matches = normalized.count(old) if old else 0
        if matches != 1:
            return ActionResult(Outcome.REJECTED, {"matches": matches}, "exact_match_required").payload()
        updated = normalized.replace(old, new_text.replace("\r\n", "\n").replace("\r", "\n"), 1)
        if "\r\n" in content:
            updated = updated.replace("\n", "\r\n")
        if target.suffix.lower() == ".py":
            compile(updated, str(target), "exec")
        atomic_write_bytes(target, updated.encode(encoding))
        return ActionResult(Outcome.SUCCESS, {"path": str(target), "restart_required": True}).payload()
    except (ValueError, UnicodeError, SyntaxError, FileNotFoundError) as error:
        return ActionResult(Outcome.REJECTED, str(error), "source_precondition").payload()
    except OSError as error:
        return ActionResult(Outcome.FAILED, str(error), "source_write_failed").payload()


def create_code(path: str, content: str) -> dict:
    """Create a new assistant source file without overwriting, under a supervised mutation contract.
    Parent directory must exist. Python syntax is validated before an atomic exclusive publication.
    """
    import os
    import tempfile
    temporary = None
    try:
        target = _path(path)
        if target.exists() or not target.parent.is_dir():
            return ActionResult(Outcome.REJECTED, str(target), "new_source_path_required").payload()
        if target.suffix.lower() == ".py":
            compile(content, str(target), "exec")
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
            temporary = stream.name
            stream.write(content.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, target)
        return ActionResult(Outcome.SUCCESS, {"path": str(target), "restart_required": True}).payload()
    except (ValueError, SyntaxError, FileExistsError) as error:
        return ActionResult(Outcome.REJECTED, str(error), "source_precondition").payload()
    except OSError as error:
        return ActionResult(Outcome.FAILED, str(error), "source_create_failed").payload()
    finally:
        if temporary is not None:
            os.unlink(temporary)


def verify_code(path: str) -> dict:
    """Independently inspect and compile current Python source without writing bytecode or running it."""
    from .brain import decode_text
    try:
        target = _path(path)
        if target.suffix.lower() != ".py":
            return ActionResult(Outcome.REJECTED, str(target), "python_source_required").payload()
        content, _ = decode_text(target.read_bytes())
        compile(content, str(target), "exec")
        return ActionResult(Outcome.SUCCESS, {"path": str(target), "syntax_valid": True}).payload()
    except (OSError, ValueError, UnicodeError, SyntaxError) as error:
        return ActionResult(Outcome.FAILED, str(error), "source_verification_failed").payload()


def update_repo() -> dict:
    """Fast-forward the assistant's upstream only when explicitly requested, refusing local changes."""
    from .brain import run_git
    try:
        status = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "status", "--porcelain", "--untracked-files=all"],
            capture_output=True, text=True, errors="replace", timeout=15)
        if status.returncode:
            return ActionResult(Outcome.FAILED, status.stderr, "git_status_failed").payload()
        if status.stdout.strip():
            return ActionResult(Outcome.REJECTED, status.stdout, "clean_repository_required").payload()
        return run_git(str(PROJECT_ROOT), ["pull", "--ff-only"])
    except (OSError, subprocess.TimeoutExpired) as error:
        return ActionResult(Outcome.UNCERTAIN, str(error), "update_state_unknown").payload()
