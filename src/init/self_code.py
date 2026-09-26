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
import json
import logging
import subprocess
from src.init.visuals.browser_bridge import open_embedded_url
from src.init.paths import ARLO_ROOT
from .task_outcomes import ActionResult, Outcome, normalize_result

READ_CODE_MAX_CHARACTERS = 3000
READ_CODE_MAX_LINES = 160
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
    target = (ARLO_ROOT / path).resolve()
    relative = target.relative_to(ARLO_ROOT)
    if any(part.casefold() in (".git", ".venv", "__pycache__") for part in relative.parts):
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
        if not observation.successful:
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
        logging.getLogger("arlo.context").info(
            "Bounded list_code source=%s entries=%d returned=%d offset=%d bytes=%d",
            directory, len(entries), len(selected), offset,
            len(output.encode("utf-8")))
        return ActionResult(Outcome.SUCCESS, output).payload()
    except (OSError, ValueError) as error:
        return ActionResult(Outcome.REJECTED, str(error), "inspection_precondition").payload()


def search_code(query: str, directory: str = ".",
                suffix: str = ".py",
                limit: int = SEARCH_CODE_MAX_RESULTS) -> dict:
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
            return ActionResult(Outcome.NEGATIVE, {"matches": [], "query": query}, "no_matches").payload()

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

        return ActionResult(Outcome.SUCCESS, output).payload()

    except (OSError, ValueError) as error:
        return ActionResult(Outcome.REJECTED, str(error), "inspection_precondition").payload()


def read_code(path: str, start_line: int = 1, end_line: int = 0,
              character_offset: int = 0) -> dict:
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
            return ActionResult(Outcome.SUCCESS, output).payload()
        if start_line > max(total_lines, 1):
            raise ValueError(f"start_line exceeds the file's {total_lines} lines")
        requested_end = end_line or min(total_lines, start_line + READ_CODE_MAX_LINES - 1)
        bounded_end = min(requested_end, total_lines,
                          start_line + READ_CODE_MAX_LINES - 1)
        block = "".join(lines[start_line - 1:bounded_end])
        allowance = _inspection_allowance(
            max(0, len(block) - character_offset))
        if allowance == 0:
            return ActionResult(Outcome.NEGATIVE, f"No source characters at offset {character_offset} in this range.").payload()
        if (start_line == 1 and not end_line and character_offset == 0
                and len(result) <= READ_CODE_MAX_CHARACTERS
                and allowance == len(result)):
            return ActionResult(Outcome.SUCCESS, result).payload()
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
        return ActionResult(Outcome.SUCCESS, output).payload()
    except (OSError, ValueError) as error:
        return ActionResult(Outcome.REJECTED, str(error), "inspection_precondition").payload()


def edit_code(path: str, old_text: str, new_text: str) -> dict:
    """Replace exactly one existing fragment in Arlo source, validating Python before atomic writes."""
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
    """Create a new Arlo source file without overwriting, under a supervised mutation contract.
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
    """Fast-forward Arlo's upstream only when explicitly requested, refusing local changes."""
    from .brain import run_git
    try:
        status = subprocess.run(
            ["git", "-C", str(ARLO_ROOT), "status", "--porcelain", "--untracked-files=all"],
            capture_output=True, text=True, errors="replace", timeout=15)
        if status.returncode:
            return ActionResult(Outcome.FAILED, status.stderr, "git_status_failed").payload()
        if status.stdout.strip():
            return ActionResult(Outcome.REJECTED, status.stdout, "clean_repository_required").payload()
        return run_git(str(ARLO_ROOT), ["pull", "--ff-only"])
    except (OSError, subprocess.TimeoutExpired) as error:
        return ActionResult(Outcome.UNCERTAIN, str(error), "update_state_unknown").payload()
