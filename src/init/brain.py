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
#type: ignore

from src.init.lang import tr
import base64
import codecs
import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import wave
from src.init.visuals.browser_bridge import open_embedded_url
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import lru_cache
from math import asin, cos, radians, sin, sqrt
from src.init.identity import get_assistant_name
from pathlib import Path
from urllib.parse import urlencode, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import unicodedata
import winshell

from .identity import get_assistant
from .task_outcomes import ActionResult, Outcome

try:
    import winreg
except ImportError:
    winreg = None

from src.init.config import (CONFIG_FILE, HOME_PATH, ensure_storage, load_config,
                     save_config, load_dev_file, update_config)
from src.init.app_cache import cached_app, remember_app, forget_app
from src.init.steam import steam_manager
from src.init.voice_profiles import (VOICE_DIR, MODEL_DIR, VOICE_MODEL,
                             VOICE_REFERENCE, VOICE_REFERENCE_TEXT)
from src.init.desktop.capture import request_screenshot

VERSION = "no-version-found"

MODEL_NAME = os.environ.get("MODEL", load_dev_file()["model_name"])
OLLAMA_KEEP_ALIVE = os.environ.get("KEEP_ALIVE",
                                   load_config().get("keep_alive"))
GIT_TIMEOUT_SECONDS = int(os.environ.get("GIT_TIMEOUT", "120"))
NOMINATIM_BASE_URL = os.environ.get(
    "GEOCODER_URL", "https://nominatim.openstreetmap.org").rstrip("/")
OSRM_BASE_URL = os.environ.get(
    "ROUTER_URL", "https://router.project-osrm.org").rstrip("/")
NOMINATIM_MIN_INTERVAL_SECONDS = 1.05
_GEOCODE_CACHE: dict[str, dict[str, object] | None] = {}
_GEOCODE_LOCK = threading.Lock()
NOTES_FILE = HOME_PATH / "note" / f"{datetime.now():%Y-%m-%d_%H-%M-%S_%f}.txt"
APPLICATION_SUFFIXES = (".exe", ".com", ".bat", ".cmd", ".lnk", ".appref-ms")
_APPLICATION_SEARCH_CACHE: dict[str, list[dict[str, str]]] = {}

_LAST_GEOCODE_REQUEST_AT = 0.0



def kill_self() -> str:
    """Close the assistant application gracefully, only when the user explicitly asks to exit.
    Requests shutdown after the current turn; never shuts down Windows or
    terminates another application or the shared model/voice services.
    """
    get_assistant().shutdown_requested.set()
    return f"{get_assistant_name()} shutdown requested."


def get_version() -> str:
    """Return the assistant's current version from its application configuration."""
    try:
        return load_dev_file()["version"]
    except (OSError, ValueError):
        return VERSION


def refresh() -> str:
    """Reload loaded assistant Python modules and rebuild model tools without restarting.

    Use this when the user asks to refresh, reload, or update the assistant's modules
    or source code. Modules under src.init and src.diagnostics are included.
    """
    try:
        return get_assistant().reload_source()
    except Exception as error:
        return tr('brain.error_at_refresh_attempt', error=error)


def keep_model_loaded() -> None:
    """Extend Ollama's model lifetime without delaying the next prompt."""
    payload = json.dumps({
        "model": MODEL_NAME,
        "prompt": "",
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "stream": False,
    }).encode("utf-8")
    request = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5):
            pass
    except (OSError, TimeoutError):
        pass


def refresh_model_keep_alive() -> None:
    """Refresh Ollama's keep-alive timer in the background."""
    threading.Thread(target=keep_model_loaded, daemon=True).start()


def get_working_directory() -> str:
    """Return the current directory used by relative file and Git operations."""
    from .paths import session_directory
    return str(session_directory())


def change_directory(path: str = "") -> str:
    """Persistently change the assistant's working directory; empty path reports it.
    Accepts relative or absolute paths, Windows drive paths, quotes, ~ and
    environment variables. Subsequent tools resolve relative paths here.
    """
    from .sessions import execution_identity
    session = execution_identity().session
    try:
        path = path.strip()
        if not path:
            session.show_working_directory = True
            return get_working_directory()
        if len(path) >= 2 and path[0] == path[-1] and path[0] in "\"'":
            path = path[1:-1]
        if not path:
            return tr('brain.error_directory_path_is_empty')
        destination = resolve_safe_path(os.path.expandvars(path))
        if not destination.is_dir():
            raise NotADirectoryError(str(destination))
        session.working_directory = destination
        session.show_working_directory = True
        return tr('brain.current_directory', value0=get_working_directory())
    except (OSError, ValueError) as error:
        return f"Error: {error}"


@lru_cache(maxsize=1)
def _timezone_finder():
    from timezonefinder import TimezoneFinder

    return TimezoneFinder()


def get_current_time(region: str = "") -> str:
    """Return current time for a place name or IANA zone (e.g. Europe/Madrid).
    Pass the user's city/region as stated, including country when known.
    Empty region returns the computer's local time. Place names require geocoding;
    IANA zones work offline. The result includes the resolved place and UTC offset.
    """
    if not isinstance(region, str):
        return tr('brain.error_region_must_be_a_string')
    region = region.strip()
    if not region:
        return datetime.now().astimezone().strftime(
            "%Y-%m-%d %H:%M:%S %Z (UTC%z)")
    try:
        place_name = region
        try:
            zone = ZoneInfo(region)
        except ZoneInfoNotFoundError:
            if "/" in region or region.upper() == "UTC":
                return tr('brain.error_unknown_timezone_or_missing_tzdata', region=region)
            place = geocode_city(region)
            if place is None:
                return tr('brain.error_location_not_found_87fb59', region=region)
            zone_name = _timezone_finder().timezone_at(
                lat=place["latitude"], lng=place["longitude"])
            if zone_name is None:
                return tr('brain.error_timezone_not_found_for', region=region)
            zone = ZoneInfo(zone_name)
            place_name = place["name"]
        current = datetime.now(zone)
        return f"{place_name}: {current:%Y-%m-%d %H:%M:%S} ({zone.key}, UTC{current:%z})"
    except ImportError:
        return tr('brain.error_timezone_dependencies_missing_run_pip_install_r_requiremen')
    except Exception as error:
        return tr('brain.error_getting_current_time_for', region=region, error=error)


def calculate(expression: str) -> str:
    if not set(expression) <= set("0123456789+-*/(). "):
        return tr('brain.error_only_numbers_and_arithmetic_operators_are_allowed')
    try:
        return str(eval(expression, {"__builtins__": {}}, {}))
    except Exception as error:
        return f"Error: {error}"


def save_note(note: str) -> str:
    ensure_storage()
    with NOTES_FILE.open("a", encoding="utf-8") as file:
        file.write(f"{note}\n")
    return tr('brain.note_saved')


def read_notes() -> str:
    ensure_storage()
    notes = sorted((HOME_PATH / "note").glob("*.txt"))
    return "\n\n".join(
        f"{path.name}\n{path.read_text(encoding='utf-8')}" for path in
        notes) if notes else tr('brain.no_notes_saved_yet')


def list_files(path: str = ".", recursive: bool = False,
               suffix: str = "") -> dict:
    """List directory entries, optionally recursively and filtered by file suffix."""
    try:
        folder = resolve_safe_path(path)
        if not folder.exists():
            return ActionResult(Outcome.NEGATIVE, tr('brain.directory_does_not_exist', folder=folder), "missing_resource").payload()
        if not folder.is_dir():
            return ActionResult(Outcome.REJECTED, tr('brain.not_a_directory', folder=folder), "file_precondition").payload()
        normalized_suffix = suffix.strip().casefold()
        if normalized_suffix and not normalized_suffix.startswith("."):
            normalized_suffix = "." + normalized_suffix
        items = []
        if recursive:
            for current, directories, files in os.walk(folder, followlinks=False):
                directories[:] = sorted(
                    name for name in directories
                    if name not in {".git", ".venv", "__pycache__"}
                    and not (Path(current) / name).is_symlink())
                current_path = Path(current)
                if not normalized_suffix:
                    items.extend(
                        f"[DIR] {(current_path / name).relative_to(folder)}"
                        for name in directories)
                items.extend(
                    f"[FILE] {(current_path / name).relative_to(folder)}"
                    for name in sorted(files)
                    if not normalized_suffix
                    or Path(name).suffix.casefold() == normalized_suffix)
        else:
            for item in folder.iterdir():
                if (normalized_suffix
                        and (not item.is_file()
                             or item.suffix.casefold() != normalized_suffix)):
                    continue
                kind = "DIR" if item.is_dir() else "FILE"
                items.append(f"[{kind}] {item.name}")
        items.sort(key=str.casefold)
        if normalized_suffix and not items:
            scope = "recursively" if recursive else "in the directory root"
            return ActionResult(Outcome.NEGATIVE, f"No files ending in {normalized_suffix} were found {scope}.", "observed").payload()
        return ActionResult(Outcome.SUCCESS, "\n".join(items) if items else tr('brain.directory_is_empty'), "observed").payload()
    except Exception as error:
        return ActionResult(Outcome.FAILED, f"Error: {error}", "file_operation_failed").payload()


def find_directories(name: str, directory: str = "", partial: bool = False,
                     max_results: int = 100, timeout_seconds: int = 30,
                     refresh: bool = False) -> str:
    """Find folders: cache first, then all local disks unless directory is specified.

    Returns every matching absolute path and search completeness. Duplicates
    require user selection. refresh=True bypasses cache. Explicit directory
    searches only that subtree. Does not follow links or junctions.
    """
    from .folder_search import search_folders
    try:
        return json.dumps(search_folders(name, directory, partial, max_results,
                                         timeout_seconds, refresh), ensure_ascii=False)
    except (OSError, ValueError) as error:
        return tr('brain.error_searching_directories', error=error)


def create_directory(path: str, parents: bool = True) -> dict:
    """Create a directory; optionally create all missing parent directories."""
    try:
        directory_path = resolve_safe_path(path)
        if directory_path.exists():
            if directory_path.is_dir():
                return ActionResult(Outcome.SUCCESS, tr('brain.directory_already_exists', directory_path=directory_path), "observed").payload()
            return ActionResult(Outcome.REJECTED, tr('brain.a_file_already_exists_at', directory_path=directory_path), "file_precondition").payload()
        directory_path.mkdir(parents=parents, exist_ok=False)
        return ActionResult(Outcome.SUCCESS, tr('brain.directory_created', directory_path=directory_path), "observed").payload()
    except Exception as error:
        return ActionResult(Outcome.FAILED, f"Error: {error}", "file_operation_failed").payload()


def rename_directory(path: str, new_name: str) -> dict:
    """Rename a directory in place; new_name must be a name, not another path."""
    try:
        directory_path = resolve_entry_path(path)
        if not directory_path.exists():
            return ActionResult(Outcome.NEGATIVE, tr('brain.directory_does_not_exist_d689f2', directory_path=directory_path), "missing_resource").payload()
        if not directory_path.is_dir():
            return ActionResult(Outcome.REJECTED, tr('brain.not_a_directory_a06036', directory_path=directory_path), "file_precondition").payload()
        if (not new_name.strip() or new_name in (".", "..")
                or Path(new_name).name != new_name):
            return ActionResult(Outcome.REJECTED, tr('brain.invalid_directory_name', new_name=new_name), "file_precondition").payload()
        destination = directory_path.with_name(new_name)
        if destination.exists() or destination.is_symlink():
            return ActionResult(Outcome.REJECTED, tr('brain.destination_already_exists', destination=destination), "file_precondition").payload()
        directory_path.rename(destination)
        return ActionResult(Outcome.SUCCESS, tr('brain.directory_renamed', directory_path=directory_path, destination=destination), "observed").payload()
    except Exception as error:
        return ActionResult(Outcome.FAILED, f"Error: {error}", "file_operation_failed").payload()


def delete_directory(path: str, recursive: bool = False) -> dict:
    """Delete a directory; recursive must be true to remove any contents."""
    try:
        directory_path = resolve_entry_path(path)
        if not directory_path.exists() and not directory_path.is_symlink():
            return ActionResult(Outcome.NEGATIVE, tr('brain.directory_does_not_exist_d689f2', directory_path=directory_path), "missing_resource").payload()
        if not directory_path.is_dir():
            return ActionResult(Outcome.REJECTED, tr('brain.not_a_directory_a06036', directory_path=directory_path), "file_precondition").payload()
        if directory_path == Path(directory_path.anchor):
            return ActionResult(Outcome.REJECTED, tr('brain.refusing_to_delete_a_filesystem_root', directory_path=directory_path), "file_precondition").payload()

        is_junction = (hasattr(directory_path, "is_junction")
                       and directory_path.is_junction())
        if directory_path.is_symlink():
            directory_path.unlink()
        elif is_junction:
            directory_path.rmdir()
        elif recursive:
            shutil.rmtree(directory_path)
        elif any(directory_path.iterdir()):
            return ActionResult(Outcome.REJECTED, tr('brain.directory_is_not_empty_recursive_deletion_was_not_requested',
                      directory_path=directory_path), "file_precondition").payload()
        else:
            directory_path.rmdir()
        return ActionResult(Outcome.SUCCESS, tr('brain.directory_deleted', directory_path=directory_path), "observed").payload()
    except Exception as error:
        return ActionResult(Outcome.FAILED, f"Error: {error}", "file_operation_failed").payload()


def read_file(path: str, offset: int = 0, limit: int = 2000) -> dict:
    """Read a bounded text page; continue with next_offset until exhausted."""
    try:
        file_path = resolve_safe_path(path)
        if _is_arlo_source_path(file_path):
            return (
                ActionResult(Outcome.REJECTED, f"SELF_CODE_REQUIRED: This path belongs to {get_assistant_name()}'s own repository. "
                "Use search_code/read_code for source inspection. "
                "Do not retry read_file for this path.", "self_code_required").payload())
        
        from .attachments import active_attachments
        attachments = active_attachments.get()
        if offset < 0 or limit < 1:
            return ActionResult(Outcome.REJECTED, "Use a nonnegative offset and a positive limit", "file_precondition").payload()
        if attachments is not None:
            from .attachments import normalized_path
            item = next((item for item in attachments.items.values()
                         if normalized_path(item.path) == normalized_path(str(file_path))), None)
            if item is not None:
                return ActionResult(Outcome.REJECTED, {"attachment_id": item.id,
                                    "next_action": "Use read_attachment; its offsets and limits follow the attachment format."},
                                    "attachment_tool_required").payload()
        if not file_path.exists():
            return ActionResult(Outcome.NEGATIVE, tr('brain.file_does_not_exist', file_path=file_path), "missing_resource").payload()
        if not file_path.is_file():
            return ActionResult(Outcome.REJECTED, tr('brain.not_a_file', file_path=file_path), "file_precondition").payload()
        raw = file_path.read_bytes()
        content, _ = decode_text(raw)
        if offset > len(content):
            return ActionResult(Outcome.REJECTED, "Offset exceeds file contents", "file_precondition").payload()
        end = min(len(content), offset + min(limit, 2000))
        return ActionResult(Outcome.SUCCESS, {"content": content[offset:end], "offset": offset,
                            "next_offset": end if end < len(content) else None,
                            "total_characters": len(content), "exhausted": end == len(content),
                            "revision": hashlib.sha256(raw).hexdigest()}, "observed").payload()
    except Exception as error:
        return ActionResult(Outcome.FAILED, f"Error: {error}", "file_operation_failed").payload()


def create_file(path: str, content: str = "", encoding: str = "utf-8") -> dict:
    """Create a new text file and fail rather than overwrite an existing file."""
    try:
        file_path = resolve_safe_path(path)
        if _is_arlo_source_path(file_path):
            return (
                ActionResult(Outcome.REJECTED, f"SELF_CODE_REQUIRED: This path belongs to {get_assistant_name()}'s own repository. "
                f"Use create_code to create {get_assistant_name()} source. "
                "Do not retry create_file for this path.", "self_code_required").payload())
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with file_path.open("x", encoding=encoding) as file:
            file.write(content)
        return ActionResult(Outcome.SUCCESS, tr('brain.file_created', file_path=file_path), "observed").payload()
    except FileExistsError:
        return ActionResult(Outcome.REJECTED, tr('brain.file_already_exists', value0=resolve_safe_path(path)), "file_precondition").payload()
    except (LookupError, OSError) as error:
        return ActionResult(Outcome.FAILED, f"Error: {error}", "file_operation_failed").payload()


def write_file(path: str, content: str) -> str:
    """Create or completely overwrite a UTF-8 text file."""
    try:
        file_path = resolve_safe_path(path)
        if _is_arlo_source_path(file_path):
            return (
                f"SELF_CODE_REQUIRED: This path belongs to {get_assistant_name()}'s own repository. "
                f"Use edit_code to modify {get_assistant_name()} source. "
                "Do not retry write_file for this path.")
        atomic_write_bytes(file_path, content.encode("utf-8"))
        return tr('brain.file_written', file_path=file_path)
    except Exception as error:
        return f"Error: {error}"


def edit_file(path: str, content: str) -> dict:
    """Replace the entire contents of an existing user file.
    Use for files in the user's current working directory.
    Do not use to modify the assistant's own source code; use edit_code instead.
    Args:
        path: Path to the existing user file.
        content: Complete replacement contents of the file.
    """
    try:
        file_path = resolve_safe_path(path)
        if _is_arlo_source_path(file_path):
            return (
                ActionResult(Outcome.REJECTED, f"SELF_CODE_REQUIRED: This path belongs to {get_assistant_name()}'s own repository. "
                f"Use edit_code to modify {get_assistant_name()} source. "
                "Do not retry edit_file for this path.", "self_code_required").payload())
        if not file_path.exists():
            return ActionResult(Outcome.NEGATIVE, tr('brain.file_does_not_exist', file_path=file_path), "missing_resource").payload()
        if not file_path.is_file():
            return ActionResult(Outcome.REJECTED, tr('brain.not_a_file', file_path=file_path), "file_precondition").payload()
        _, encoding = decode_text(file_path.read_bytes())
        atomic_write_bytes(file_path, content.encode(encoding))
        return ActionResult(Outcome.SUCCESS, tr('brain.file_edited', file_path=file_path), "observed").payload()
    except Exception as error:
        return ActionResult(Outcome.FAILED, f"Error: {error}", "file_operation_failed").payload()


def append_file(path: str, content: str) -> dict:
    """Append text to a file, preserving its existing text encoding."""
    try:
        file_path = resolve_safe_path(path)
        if _is_arlo_source_path(file_path):
            return (
                ActionResult(Outcome.REJECTED, f"SELF_CODE_REQUIRED: This path belongs to {get_assistant_name()}'s own repository. "
                f"Use edit_code to modify {get_assistant_name()} source. "
                "Do not retry append_file for this path.", "self_code_required").payload())
        file_path.parent.mkdir(parents=True, exist_ok=True)
        encoding = "utf-8"
        if file_path.exists():
            if not file_path.is_file():
                return ActionResult(Outcome.REJECTED, tr('brain.not_a_file', file_path=file_path), "file_precondition").payload()
            _, encoding = decode_text(file_path.read_bytes())
        with file_path.open("a", encoding=encoding) as file:
            file.write(content)
        return ActionResult(Outcome.SUCCESS, tr('brain.content_appended_to', file_path=file_path), "observed").payload()
    except Exception as error:
        return ActionResult(Outcome.FAILED, f"Error: {error}", "file_operation_failed").payload()


def replace_in_file(path: str, old_text: str, new_text: str) -> dict:
    """Replace matching text in an existing file without changing its encoding."""
    try:
        file_path = resolve_safe_path(path)
        if _is_arlo_source_path(file_path):
            return (
                ActionResult(Outcome.REJECTED, f"SELF_CODE_REQUIRED: This path belongs to {get_assistant_name()}'s own repository. "
                f"Use edit_code to modify {get_assistant_name()} source. "
                "Do not retry replace_in_file for this path.", "self_code_required").payload())
        if not file_path.exists():
            return ActionResult(Outcome.NEGATIVE, tr('brain.file_does_not_exist', file_path=file_path), "missing_resource").payload()
        if not file_path.is_file():
            return ActionResult(Outcome.REJECTED, tr('brain.not_a_file', file_path=file_path), "file_precondition").payload()
        content, encoding = decode_text(file_path.read_bytes())
        if old_text not in content:
            return ActionResult(Outcome.REJECTED, tr('brain.text_to_replace_was_not_found'), "file_precondition").payload()
        occurrences = content.count(old_text)
        updated_content = content.replace(old_text, new_text)
        atomic_write_bytes(file_path, updated_content.encode(encoding))
        return ActionResult(Outcome.SUCCESS, tr('brain.replaced_occurrence_s_in', occurrences=occurrences, file_path=file_path), "observed").payload()
    except Exception as error:
        return ActionResult(Outcome.FAILED, f"Error: {error}", "file_operation_failed").payload()


def run_git(repository: str, arguments: list[str]) -> dict:
    """Run an internally selected Git operation and retain its actual exit status."""
    try:
        repository_path = resolve_safe_path(repository)
        if not repository_path.is_dir():
            return ActionResult(Outcome.REJECTED, str(repository_path), "repository_required").payload()
        if shutil.which("git") is None:
            return ActionResult(Outcome.EXTERNAL_BLOCKER, "Git is unavailable", "dependency_unavailable",
                                "git_executable", "Install Git or make it available on PATH.").payload()
        environment = os.environ.copy()
        environment["GIT_TERMINAL_PROMPT"] = "0"
        result = subprocess.run(
            ["git", "-C", str(repository_path), "--no-pager", *arguments],
            capture_output=True, text=True, errors="replace", timeout=GIT_TIMEOUT_SECONDS,
            env=environment)
        return ActionResult(Outcome.SUCCESS if result.returncode == 0 else Outcome.FAILED,
                            {"stdout": result.stdout, "stderr": result.stderr,
                             "exit_code": result.returncode}, "git_result").payload()
    except subprocess.TimeoutExpired:
        return ActionResult(Outcome.UNCERTAIN, "Git timed out; inspect before retrying.", "timeout").payload()
    except OSError as error:
        return ActionResult(Outcome.FAILED, str(error), "git_execution_failed").payload()


def valid_git_name(value: str, label: str) -> str | None:
    """Reject empty or option-like Git names before passing them to Git."""
    if not value or value.startswith("-") or "\x00" in value:
        return tr('brain.error_invalid_git', label=label, value=value)
    if label == "branch":
        forbidden_characters = set(" ~^:?*[\\")
        invalid_structure = (
                value.startswith(".")
                or value.endswith(("/", "."))
                or ".." in value
                or "//" in value
                or "@{" in value
                or value.endswith(".lock")
        )
        if forbidden_characters.intersection(value) or invalid_structure:
            return tr('brain.error_invalid_git_branch', value=value)
    return None


def git_status(repository: str = ".") -> dict:
    """Show the current branch and concise working-tree status for a repository."""
    return run_git(repository, ["status", "--short", "--branch"])


def git_diff(repository: str = ".", staged: bool = False,
             path: str = "") -> dict:
    """Show unstaged changes, or staged changes when staged is true."""
    arguments = ["diff", "--no-ext-diff"]
    if staged:
        arguments.append("--staged")
    if path:
        arguments.extend(["--", path])
    result = run_git(repository, arguments)
    if result["outcome"] == Outcome.SUCCESS and not result["data"]["stdout"]:
        return ActionResult(Outcome.NEGATIVE, result["data"], "no_differences").payload()
    return result


def git_add(paths: list[str], repository: str = ".") -> dict:
    """Stage the exact files or pathspecs supplied in paths for a later commit."""
    if not paths or any(not path or "\x00" in path for path in paths):
        return ActionResult(Outcome.REJECTED, tr('brain.error_provide_at_least_one_valid_path_to_stage'), "git_precondition").payload()
    return run_git(repository, ["add", "--", *paths])


def git_commit(message: str, repository: str = ".") -> dict:
    """Create a commit from staged changes with the supplied commit message."""
    if not message.strip() or "\x00" in message:
        return ActionResult(Outcome.REJECTED, tr('brain.error_commit_message_cannot_be_empty'), "git_precondition").payload()
    return run_git(repository, ["commit", "-m", message])


def git_fetch(repository: str = ".", remote: str = "",
              prune: bool = False) -> dict:
    """Download remote refs without changing local files or the current branch."""
    arguments = ["fetch"]
    if prune:
        arguments.append("--prune")
    if remote:
        error = valid_git_name(remote, "remote")
        if error:
            return ActionResult(Outcome.REJECTED, error, "git_precondition").payload()
        arguments.append(remote)
    return run_git(repository, arguments)


def git_pull(repository: str = ".", remote: str = "", branch: str = "",
             rebase: bool = False) -> dict:
    """Fetch and integrate a remote branch into the checked-out local branch."""
    if branch and not remote:
        return ActionResult(Outcome.REJECTED, tr('brain.error_a_remote_is_required_when_a_branch_is_supplied'), "git_precondition").payload()
    arguments = ["pull"]
    if rebase:
        arguments.append("--rebase")
    for value, label in ((remote, "remote"), (branch, "branch")):
        if value:
            error = valid_git_name(value, label)
            if error:
                return ActionResult(Outcome.REJECTED, error, "git_precondition").payload()
            arguments.append(value)
    return run_git(repository, arguments)


def git_push(repository: str = ".", remote: str = "", branch: str = "",
             set_upstream: bool = False) -> dict:
    """Publish commits to a configured remote, optionally setting the upstream."""
    if branch and not remote:
        return ActionResult(Outcome.REJECTED, tr('brain.error_a_remote_is_required_when_a_branch_is_supplied'), "git_precondition").payload()
    if set_upstream and not remote:
        return ActionResult(Outcome.REJECTED, tr('brain.error_a_remote_is_required_when_setting_the_upstream'), "git_precondition").payload()
    arguments = ["push"]
    if set_upstream:
        arguments.append("--set-upstream")
    for value, label in ((remote, "remote"), (branch, "branch")):
        if value:
            error = valid_git_name(value, label)
            if error:
                return ActionResult(Outcome.REJECTED, error, "git_precondition").payload()
            arguments.append(value)
    return run_git(repository, arguments)


def git_log(repository: str = ".", max_count: int = 10) -> dict:
    """Show a concise recent commit history."""
    if isinstance(max_count, bool) or not 1 <= max_count <= 100:
        return ActionResult(Outcome.REJECTED, tr('brain.error_max_count_must_be_between_1_and_100'), "git_precondition").payload()
    return run_git(
        repository,
        ["log", f"--max-count={max_count}", "--oneline", "--decorate"],
    )


def git_list_branches(repository: str = ".",
                      include_remote: bool = False) -> dict:
    """List local branches and, when requested, remote-tracking branches."""
    arguments = ["branch"]
    if include_remote:
        arguments.append("--all")
    return run_git(repository, arguments)


def git_switch(branch: str, repository: str = ".",
               create: bool = False) -> dict:
    """Switch branches, optionally creating the named branch first."""
    error = valid_git_name(branch, "branch")
    if error:
        return ActionResult(Outcome.REJECTED, error, "git_precondition").payload()
    arguments = ["switch"]
    if create:
        arguments.append("--create")
    arguments.append(branch)
    return run_git(repository, arguments)


def read_binary_file(path: str) -> dict:
    """Read any binary file and return its bytes encoded as Base64."""
    try:
        file_path = resolve_safe_path(path)
        if _is_arlo_source_path(file_path):
            return ActionResult(Outcome.REJECTED, f"Use read_code for {get_assistant_name()} source.", "self_code_required").payload()
        if not file_path.exists():
            return ActionResult(Outcome.NEGATIVE, tr('brain.file_does_not_exist', file_path=file_path), "missing_resource").payload()
        if not file_path.is_file():
            return ActionResult(Outcome.REJECTED, tr('brain.not_a_file', file_path=file_path), "file_precondition").payload()
        encoded = base64.b64encode(file_path.read_bytes()).decode("ascii")
        return ActionResult(Outcome.SUCCESS, encoded, "observed").payload()
    except Exception as error:
        return ActionResult(Outcome.FAILED, f"Error: {error}", "file_operation_failed").payload()


def write_binary_file(path: str, base64_content: str,
                      overwrite: bool = False) -> dict:
    """Create a binary file from Base64; set overwrite only for an existing file."""
    try:
        file_path = resolve_safe_path(path)
        if _is_arlo_source_path(file_path):
            return (
                ActionResult(Outcome.REJECTED, f"SELF_CODE_REQUIRED: This path belongs to {get_assistant_name()}'s own repository. "
                f"Use edit_code to modify {get_assistant_name()} source. "
                "Do not retry write_binary_file for this path.", "self_code_required").payload())
        already_exists = file_path.exists()
        if already_exists and not overwrite:
            return ActionResult(Outcome.REJECTED, tr('brain.file_already_exists_e61309', file_path=file_path), "file_precondition").payload()
        content = base64.b64decode(base64_content, validate=True)
        atomic_write_bytes(file_path, content)
        action = "edited" if already_exists else "created"
        return ActionResult(Outcome.SUCCESS, tr('brain.binary_file', action=action, file_path=file_path), "observed").payload()
    except (ValueError, OSError) as error:
        return ActionResult(Outcome.FAILED, f"Error: {error}", "file_operation_failed").payload()


def delete_file(path: str) -> dict:
    """Permanently delete one file or symbolic link, never a directory."""
    try:
        file_path = resolve_entry_path(path)
        if not file_path.exists() and not file_path.is_symlink():
            return ActionResult(Outcome.NEGATIVE, tr('brain.file_does_not_exist', file_path=file_path), "missing_resource").payload()
        if file_path.is_dir() and not file_path.is_symlink():
            return ActionResult(Outcome.REJECTED, tr('brain.refusing_to_delete_a_directory', file_path=file_path), "file_precondition").payload()
        file_path.unlink()
        return ActionResult(Outcome.SUCCESS, tr('brain.file_deleted', file_path=file_path), "observed").payload()
    except Exception as error:
        return ActionResult(Outcome.FAILED, f"Error: {error}", "file_operation_failed").payload()


def open_file(path: str) -> str:
    try:
        target = resolve_safe_path(path)
        if not target.exists():
            return tr('brain.path_does_not_exist', target=target)
        if os.name == "nt":
            os.startfile(target)
        elif os.name == "posix":
            opener = "open" if shutil.which("open") else "xdg-open"
            subprocess.Popen([opener, str(target)])
        else:
            return tr('brain.unsupported_operating_system')
        return f"Opened: {target}"
    except Exception as error:
        return f"Error: {error}"


def open_directory(path: str = ".") -> str:
    """Open a folder in the file manager, without changing working directory.

    Accepts paths, ~ or home, Documentos/Documents, Escritorio/Desktop,
    Descargas/Downloads. Default '.' opens the current working directory.
    Bare names use folders.json first, then all disks. Multiple matches or an
    incomplete search return candidates for user selection without opening any.
    Uses Windows' configured folder locations, including redirected folders.
    """
    try:
        from src.init.folders import resolve_directory
        from .folder_search import is_folder_name, remember_folders, search_folders

        query = path.strip().strip("\"'")
        if is_folder_name(query):
            result = search_folders(query)
            matches = result["matches"]
            if len(matches) != 1 or not result["complete"]:
                result["status"] = "needs_input" if matches else "not_found"
                result["question"] = (
                    tr('brain.choose_the_full_path_of_the_folder_you_want_to_open')
                    if matches else tr('brain.no_folders_were_found_in_the_search'))
                return json.dumps(result, ensure_ascii=False)
            target = Path(matches[0])
        else:
            target = resolve_directory(path)
        if not target.is_dir():
            return tr('brain.error_directory_does_not_exist_or_is_not_a_folder', target=target)
        opened = open_file(str(target))
        if target.name and opened.startswith("Opened:"):
            remember_folders(target.name, [str(target)], complete=True)
        return opened
    except Exception as error:
        return tr('brain.error_opening_directory', error=error)


def open_browser(url: str) -> str:
    """Open a website in the assistant's integrated browser workspace."""
    try:
        if "://" not in url:
            url = "https://" + url
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return tr('brain.error_only_http_and_https_urls_are_allowed')
        open_embedded_url(url)
        return tr('brain.opened_browser', url=url)
    except Exception as error:
        return f"Error: {error}"


def search_web(query: str, region: str = "es-es", max_results: int = 6) -> str:
    """Show a search in the assistant's browser and return web results for inspection and citation."""
    query = query.strip()
    if not query:
        return tr('brain.error_search_query_is_empty')
    from urllib.parse import urlencode
    browser_note = ""
    try:
        open_embedded_url("https://www.google.com/search?" + urlencode({"q": query}))
    except (RuntimeError, ValueError) as error:
        browser_note = f"Embedded browser unavailable: {error}\n\n"
    try:
        from ddgs import DDGS

        result_limit = max(1, min(int(max_results), 10))
        results = list(DDGS(timeout=10).text(
            query,
            region=region,
            safesearch="moderate",
            max_results=result_limit
        ))
        if not results:
            return browser_note + tr('brain.no_web_results_found_for', query=query)
        formatted_results = []
        for index, result in enumerate(results, start=1):
            formatted_results.append(
                f"[{index}] {result.get('title', 'Untitled')}\n"
                f"URL: {result.get('href', '')}\n"
                f"Snippet: {result.get('body', '')}"
            )
        return browser_note + "\n\n".join(formatted_results)
    except Exception as error:
        return browser_note + tr('brain.error_searching_the_web', error=error)


def read_web_page(url: str, max_characters: int = 12_000,
                  show_in_browser: bool = False) -> str:
    """Read page text; show_in_browser also opens it in the assistant's browser workspace.
    Choose show_in_browser when inspecting a page together with the user.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return tr('brain.error_a_valid_http_or_https_url_is_required')
    if not 1_000 <= max_characters <= 30_000:
        return tr('brain.error_max_characters_must_be_between_1000_and_30000')
    browser_note = ""
    if show_in_browser:
        try:
            open_embedded_url(url)
        except (RuntimeError, ValueError) as error:
            browser_note = f"Embedded browser unavailable: {error}\n\n"
    try:
        from ddgs import DDGS

        result = DDGS(timeout=15).extract(url, fmt="text_plain")
        content = result.get("content", "")
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="replace")
        content = str(content).strip()
        if not content:
            return browser_note + tr('brain.no_readable_content_found_at', url=url)
        if len(content) > max_characters:
            content = content[:max_characters] + tr('brain.content_truncated')
        return browser_note + tr('brain.source_url', url=url, content=content)
    except Exception as error:
        return browser_note + tr('brain.error_reading_web_page', error=error)


def request_json(url: str, timeout: int = 15):
    """Request JSON from a public data API with the assistant's identifying user agent."""
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": f"{get_assistant().name}LocalAssistant/1.0 (personal desktop assistant)",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def geocode_city(city: str) -> dict[str, object] | None:
    """Resolve a place while respecting Nominatim's rate and cache policy."""
    global _LAST_GEOCODE_REQUEST_AT

    clean_city = city.strip()
    if not clean_city:
        return None
    cache_key = clean_city.casefold()

    with _GEOCODE_LOCK:
        if cache_key in _GEOCODE_CACHE:
            return _GEOCODE_CACHE[cache_key]

        elapsed = time.monotonic() - _LAST_GEOCODE_REQUEST_AT
        remaining = NOMINATIM_MIN_INTERVAL_SECONDS - elapsed
        if remaining > 0:
            time.sleep(remaining)

        parameters = urlencode({
            "q": clean_city,
            "format": "jsonv2",
            "limit": 1,
        })
        try:
            results = request_json(f"{NOMINATIM_BASE_URL}/search?{parameters}")
        finally:
            _LAST_GEOCODE_REQUEST_AT = time.monotonic()

        if not results:
            _GEOCODE_CACHE[cache_key] = None
            return None

        result = results[0]
        place = {
            "name": result["display_name"],
            "latitude": float(result["lat"]),
            "longitude": float(result["lon"]),
        }
        _GEOCODE_CACHE[cache_key] = place
        return place


def haversine_km(first: dict, second: dict) -> float:
    """Calculate great-circle distance between two geocoded points."""
    first_latitude = radians(first["latitude"])
    second_latitude = radians(second["latitude"])
    latitude_delta = second_latitude - first_latitude
    longitude_delta = radians(second["longitude"] - first["longitude"])
    haversine = (
            sin(latitude_delta / 2) ** 2
            + cos(first_latitude) * cos(second_latitude)
            * sin(longitude_delta / 2) ** 2
    )
    haversine = max(0.0, min(1.0, haversine))
    return 2 * 6371.0088 * asin(sqrt(haversine))


def get_city_distance(origin: str, destination: str) -> str:
    """Return verified straight-line and driving distances between two places."""
    try:
        origin_place = geocode_city(origin)
        destination_place = geocode_city(destination)
        if origin_place is None:
            return tr('brain.error_location_not_found', origin=origin)
        if destination_place is None:
            return tr('brain.error_location_not_found_dee0a3', destination=destination)

        straight_line_km = haversine_km(origin_place, destination_place)
        coordinates = (
            f"{origin_place['longitude']},{origin_place['latitude']};"
            f"{destination_place['longitude']},{destination_place['latitude']}"
        )
        route_url = (
            f"{OSRM_BASE_URL}/route/v1/driving/"
            f"{coordinates}?overview=false&alternatives=false&steps=false"
        )
        route = None
        route_error = None
        try:
            route_data = request_json(route_url)
            if route_data.get("code") == "Ok" and route_data.get("routes"):
                route = route_data["routes"][0]
            else:
                route_error = (
                    tr('brain.osrm_returned_status', value0=route_data.get('code', 'unknown'))
                )
        except Exception as error:
            route_error = tr('brain.driving_route_could_not_be_verified', error=error)

        result = {
            "origin_resolved": origin_place["name"],
            "destination_resolved": destination_place["name"],
            "straight_line_km": round(straight_line_km, 1),
            "driving_route_km": (
                round(route["distance"] / 1000, 1) if route else None
            ),
            "driving_duration_hours": (
                round(route["duration"] / 3600, 2) if route else None
            ),
            "route_error": route_error,
            "distance_notes": {
                "straight_line": (
                    tr('brain.approximate_geodesic_distance_between_the_resolved_coordinates')
                ),
                "driving_route": (
                    tr('brain.calculated_road_route_length_it_can_vary_by_route_and_conditions')
                ),
            },
            "sources": [
                f"{NOMINATIM_BASE_URL}/ — © OpenStreetMap contributors (ODbL)",
                f"{OSRM_BASE_URL}/ — data © OpenStreetMap contributors",
            ],
        }
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as error:
        return tr('brain.error_calculating_city_distance', error=error)


def kill_process(process: str, force: bool = False,
                 include_children: bool = False) -> str:
    """End a Windows process by exact PID or image name."""
    if os.name != "nt":
        return tr('brain.error_kill_process_is_only_supported_on_windows')

    target = process.strip()
    if not target:
        return tr('brain.error_process_pid_or_image_name_is_required')

    command = ["taskkill.exe"]
    if target.isdecimal():
        process_id = int(target)
        if process_id <= 4:
            return tr('brain.refusing_to_terminate_a_critical_system_pid', process_id=process_id)
        if process_id == os.getpid():
            return tr('brain.refusing_to_terminate_s_own_pid', value0=get_assistant().name, process_id=process_id)
        command.extend(["/PID", str(process_id)])
        description = f"PID {process_id}"
    else:
        forbidden_characters = set('<>:"/\\|?*')
        if forbidden_characters.intersection(target):
            return tr('brain.error_invalid_process_image_name', target=target)
        image_name = target if target.casefold().endswith(
            ".exe") else f"{target}.exe"
        protected_images = {
            "registry",
            "registry.exe",
            "system",
            "system.exe",
            "system idle process",
            "system idle process.exe",
            "csrss.exe",
            "lsass.exe",
            "services.exe",
            "smss.exe",
            "wininit.exe",
            "winlogon.exe",
            Path(sys.executable).name.casefold(),
        }
        if image_name.casefold() in protected_images:
            return tr('brain.refusing_to_terminate_a_critical_or_current_process', image_name=image_name)
        command.extend(["/IM", image_name])
        description = image_name

    if force:
        command.append("/F")
    if include_children:
        command.append("/T")

    try:
        result = subprocess.run(
            command, capture_output=True, text=True, errors="replace")
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            return tr('brain.error_terminating', description=description, value1=detail or tr('brain.taskkill_failed'))
        return tr('brain.process_terminated', description=description)
    except OSError as error:
        return f"Error: {error}"


def shutdown_computer(delay_seconds: int = 0) -> str:
    """Shut down Windows now, or schedule it after delay_seconds.
    Convert requested minutes or hours to seconds. Omit the delay for an
    immediate shutdown. Returns the operating system's result.
    """
    if os.name != "nt":
        return tr('brain.error_shutdown_computer_is_only_supported_on_windows')
    if isinstance(delay_seconds, bool) or not isinstance(delay_seconds, int):
        return tr('brain.error_delay_seconds_must_be_an_integer')
    if not 0 <= delay_seconds <= 315_360_000:
        return tr('brain.error_delay_seconds_must_be_between_0_and_315360000')

    try:
        executable = shutil.which("shutdown.exe") or "shutdown.exe"
        result = subprocess.run(
            [
                executable,
                "/s",
                "/t",
                str(delay_seconds),
                "/c",
                tr('brain.shutdown_scheduled_by', value0=get_assistant().name),
            ],
            capture_output=True,
            text=True,
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            return tr('brain.error_scheduling_shutdown', value0=detail or tr('brain.shutdown_failed'))
        return tr('brain.computer_shutdown_scheduled_in_second_s', delay_seconds=delay_seconds)
    except OSError as error:
        return f"Error: {error}"


def cancel_shutdown() -> str:
    """Cancel a shutdown that is currently pending on Windows."""
    if os.name != "nt":
        return tr('brain.error_cancel_shutdown_is_only_supported_on_windows')
    try:
        result = subprocess.run(
            ["shutdown.exe", "/a"],
            capture_output=True,
            text=True,
            errors="replace",
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            return tr('brain.error_cancelling_shutdown', value0=detail or tr('brain.no_shutdown_is_pending'))
        return tr('brain.pending_computer_shutdown_cancelled')
    except OSError as error:
        return f"Error: {error}"


def normalize_application_name(value: str) -> str:
    """Normalize an application name so matching is stable and accent-insensitive."""
    name = Path(value.strip()).stem
    name = unicodedata.normalize("NFKD", name.casefold())
    name = "".join(character for character in name
                   if not unicodedata.combining(character))
    return " ".join(re.findall(r"[a-z0-9]+", name))


def get_fixed_drive_roots() -> list[Path]:
    """Return every fixed local drive in deterministic order."""
    if os.name != "nt":
        return [Path("/")]

    roots = []
    drive_mask = ctypes.windll.kernel32.GetLogicalDrives()
    for index in range(26):
        if drive_mask & (1 << index):
            root = f"{chr(ord('A') + index)}:\\"
            if ctypes.windll.kernel32.GetDriveTypeW(root) == 3:
                roots.append(Path(root))
    return sorted(roots, key=lambda path: str(path).casefold())


def get_app_paths() -> list[dict[str, str]]:
    """Read executable paths registered by desktop applications."""
    if winreg is None:
        return []

    registry_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
    locations = (
        (winreg.HKEY_CURRENT_USER, winreg.KEY_READ),
        (winreg.HKEY_LOCAL_MACHINE,
         winreg.KEY_READ | winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE,
         winreg.KEY_READ | winreg.KEY_WOW64_32KEY),
    )
    apps = {}
    for hive, access in locations:
        try:
            with winreg.OpenKey(hive, registry_path, 0, access) as parent:
                subkey_count = winreg.QueryInfoKey(parent)[0]
                for index in range(subkey_count):
                    subkey_name = winreg.EnumKey(parent, index)
                    try:
                        with winreg.OpenKey(parent, subkey_name) as subkey:
                            executable = winreg.QueryValueEx(subkey, None)[0]
                    except OSError:
                        continue
                    executable = os.path.expandvars(str(executable)).strip('"')
                    if Path(executable).is_file():
                        key = executable.casefold()
                        apps[key] = {
                            "Name": Path(subkey_name).stem,
                            "Path": executable,
                        }
        except OSError:
            continue
    return sorted(apps.values(), key=lambda app: (
        normalize_application_name(app["Name"]), app["Path"].casefold()))


def get_applications() -> list[dict[str, str]]:
    """Read applications registered with Windows."""
    if os.name != "nt":
        return []
    start_apps = []
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", "Get-StartApps | "
                                                         "Select-Object Name,AppID | "
                                                         "ConvertTo-Json -Compress"],
            capture_output=True, text=True, encoding="utf-8")
        if result.returncode == 0:
            data = json.loads(result.stdout or "[]")
            start_apps = data if isinstance(data, list) else [data]
    except (OSError, json.JSONDecodeError):
        pass

    apps = [app for app in start_apps
            if app.get("Name") and app.get("AppID")]
    apps.extend(get_app_paths())
    return sorted(apps, key=lambda app: (
        normalize_application_name(app["Name"]),
        app.get("AppID", app.get("Path", "")).casefold()))


def find_applications_on_drive(root: Path, query: str) -> list[dict[str, str]]:
    """Find matching launchable files below one drive root."""
    matches = []
    for folder, folders, filenames in os.walk(
            root, onerror=lambda _: None, followlinks=False):
        folders[:] = [name for name in folders
                      if not Path(folder, name).is_junction()]
        for filename in filenames:
            path = Path(folder, filename)
            if not filename.casefold().endswith(APPLICATION_SUFFIXES):
                continue
            if query in normalize_application_name(filename):
                matches.append({
                    "Name": path.stem,
                    "Path": str(path),
                    "Source": "file",
                })
    return matches


def find_applications_on_all_drives(application: str) -> list[dict[str, str]]:
    """Find launchable files on every fixed disk, caching each normalized query."""
    query = normalize_application_name(application)
    if not query:
        return []
    if query in _APPLICATION_SEARCH_CACHE:
        return _APPLICATION_SEARCH_CACHE[query]

    roots = get_fixed_drive_roots()
    matches = []
    if roots:
        with ThreadPoolExecutor(max_workers=len(roots)) as executor:
            for drive_matches in executor.map(
                    lambda root: find_applications_on_drive(root, query),
                    roots):
                matches.extend(drive_matches)

    matches.sort(key=lambda app: (normalize_application_name(app["Name"]),
                                  app["Path"].casefold()))
    _APPLICATION_SEARCH_CACHE[query] = matches
    return matches


def application_rank(app: dict[str, str], query: str) -> tuple:
    """Return a deterministic relevance order for an application candidate."""
    name = normalize_application_name(app["Name"])
    if name == query:
        match_rank = 0
    elif name.startswith(query):
        match_rank = 1
    elif all(word in name.split() for word in query.split()):
        match_rank = 2
    else:
        match_rank = 3

    helper_words = {"crash", "helper", "installer", "setup", "uninstall",
                    "update"}
    helper_rank = int(bool(helper_words.intersection(name.split())))
    source_rank = 0 if app["Source"] == "registered" else 1
    target = app.get("AppID", app.get("Path", ""))
    return match_rank, helper_rank, source_rank, name, target.casefold()


def list_applications() -> str:
    """List INSTALLED applications available to launch, NOT currently open apps."""
    apps = get_applications()
    if not apps:
        return tr('brain.no_applications_found')
    return "\n".join(sorted(app["Name"] for app in apps))


def list_open_applications() -> str:
    """List current taskbar-style windows, including minimized applications.

    Use for 'what apps are open' or taskbar requests. Excludes background-only
    processes, tray-only apps and installed/pinned apps without an open window.
    Enumerates standard visible windows on the current desktop; custom Shell
    taskbar registration or virtual-desktop settings may differ.
    """
    if os.name != "nt":
        return tr('brain.error_listing_open_applications_is_only_supported_on_windows')
    try:
        from src.init.windows import get_open_windows

        return json.dumps({"open_windows": get_open_windows()},
                          ensure_ascii=False, indent=2)
    except Exception as error:
        return tr('brain.error_listing_open_applications', error=error)


def _launch_application(app):
    from src.init.windows import launch_application

    target = app.get("Path") or app.get("AppID")
    if app["Source"] == "registered" and not Path(target).is_file():
        target = f"shell:AppsFolder\\{target}"
    result = launch_application(target)
    return json.dumps({"application": app["Name"], **result}, ensure_ascii=False)


def launch_steam_game(game: str) -> str:
    """Launch an installed Steam game by its name."""
    return steam_manager.launch(game)


def list_steam_games() -> str:
    """List all installed Steam games."""
    games = steam_manager.games()
    if not games:
        return tr('brain.no_steam_games_found')

    return "\n".join(
        sorted((str(game) for game in games), key=str.casefold)
    )


def find_steam_game(game: str) -> str:
    """Find an installed Steam game by its name."""
    if steam_manager.find_game(game):
        return tr('brain.steam_game_found', value0=steam_manager.find_game(game))
    return None


def open_application(application: str) -> str:
    """Launch an app using apps.json first. Only opened=true confirms a window.

    A timeout is unconfirmed, not success; do not automatically launch again.
    """
    from src.init.folders import FOLDER_ALIASES

    raw_application = application.strip().strip('"').strip("'")
    explorer_aliases = {
        "explorador", "explorador de archivos", "file explorer",
        "windows explorer", "explorer",
    }
    if normalize_application_name(raw_application) in explorer_aliases:
        explorer = Path(os.environ.get("WINDIR", r"C:\\Windows")) / "explorer.exe"
        app = {"Name": "File Explorer", "Source": "file", "Path": str(explorer)}
        try:
            result = _launch_application(app)
            remember_app(normalize_application_name(raw_application), app)
            return result
        except Exception as error:
            return f"Error: {error}"
    if raw_application.casefold() in FOLDER_ALIASES:
        return open_directory(application)
    path_candidate = Path(os.path.expandvars(raw_application))
    path_like = ("\\" in raw_application or "/" in raw_application
                 or (len(raw_application) >= 2 and raw_application[1] == ":"))
    if path_like:
        if path_candidate.is_file() and path_candidate.suffix.casefold() in APPLICATION_SUFFIXES:
            app = {"Name": path_candidate.stem, "Source": "file",
                   "Path": str(path_candidate)}
            try:
                result = _launch_application(app)
                remember_app(normalize_application_name(path_candidate.stem), app)
                return result
            except Exception as error:
                return tr('brain.error_opening_application_path', raw_application=raw_application, error=error)
        return tr('brain.application_path_not_found_or_is_not_an_executable_file', raw_application=raw_application)

    query = raw_application.casefold()
    normalized_query = normalize_application_name(query)
    if not normalized_query:
        return tr('brain.application_name_is_empty')

    app = cached_app(normalized_query)
    if app:
        try:
            return _launch_application(app)
        except Exception:
            forget_app(normalized_query)
    _APPLICATION_SEARCH_CACHE.pop(normalized_query, None)

    registered = [
        {**app, "Source": "registered" if app.get("AppID") else "file"}
        for app in get_applications()
        if normalized_query in normalize_application_name(app["Name"])
    ]
    matches = registered or find_applications_on_all_drives(application)
    if not matches:
        return tr('brain.application_not_found', application=application)

    ranked = sorted(matches, key=lambda candidate: application_rank(candidate, normalized_query))
    app = ranked[0]
    alternatives = [candidate for candidate in ranked
                    if application_rank(candidate, normalized_query)[:2]
                    == application_rank(app, normalized_query)[:2]
                    and normalize_application_name(candidate["Name"])
                    != normalize_application_name(app["Name"])]
    if alternatives:
        return json.dumps({"status": "error", "opened": False,
                           "error": "Multiple applications match. Ask the user to choose.",
                           "candidates": [app, *alternatives]}, ensure_ascii=False)
    try:
        result = _launch_application(app)
        remember_app(normalized_query, app)
        return result
    except Exception as error:
        return f"Error: {error}"


def identify_playing_song(seconds: int = 8) -> str:
    """Listen to the computer's current output audio and identify the song."""
    if os.name != "nt":
        return tr('brain.error_system_audio_recognition_is_currently_only_supported_on_wi')

    if not 5 <= seconds <= 20:
        return tr('brain.error_seconds_must_be_between_5_and_20')

    try:
        import asyncio
        import numpy as np
        import soundcard as sc
        from shazamio import Shazam
    except ImportError:
        return (
            tr('brain.error_music_recognition_dependencies_are_not_installed_run_pip_i')
        )

    speaker = sc.default_speaker()
    if speaker is None:
        return tr('brain.error_no_default_audio_output_device_was_found')
    loopbacks = sc.all_microphones(include_loopback=True)

    loopback = next(
        (microphone
            for microphone in loopbacks
            if speaker.name.casefold() in microphone.name.casefold()
               or microphone.name.casefold() in speaker.name.casefold()),
        None,
    )

    if loopback is None:
        return tr('brain.error_no_loopback_device_found_for', value0=speaker.name)

    sample_rate = 44100
    frames = sample_rate * seconds

    try:
        with loopback.recorder(samplerate=sample_rate) as recorder:
            audio = recorder.record(numframes=frames)
    except Exception as error:
        return tr('brain.error_capturing_system_audio', error=error)

    if audio.size == 0:
        return tr('brain.no_system_audio_was_captured')

    audio = np.clip(audio, -1.0, 1.0)
    pcm = (audio * 32767).astype(np.int16)

    temporary_path = None

    try:
        with tempfile.NamedTemporaryFile(
                suffix=".wav", delete=False) as temporary_file:
            temporary_path = Path(temporary_file.name)

        with wave.open(str(temporary_path), "wb") as wav_file:
            wav_file.setnchannels(
                pcm.shape[1] if pcm.ndim > 1 else 1
            )
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm.tobytes())

        async def recognize():
            shazam = Shazam()
            return await shazam.recognize(str(temporary_path))

        result = asyncio.run(recognize())

        track = result.get("track")

        if not track:
            return tr('brain.no_song_could_be_identified_from_the_current_system_audio')

        response = {
            "title": track.get("title"),
            "artist": track.get("subtitle"),
            "album": (
                track.get("sections", [{}])[0]
                .get("metadata", [{}])[0]
                .get("text")
            ),
            "shazam_url": track.get("url"),
        }

        return json.dumps(response, ensure_ascii=False, indent=2)

    except Exception as error:
        return tr('brain.error_identifying_song', error=error)

    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


async def media_is_playing() -> bool:
    """Is media playing? Checks whether is media playing"""
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as Manager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status)

    manager = await Manager.request_async()
    return any(session.get_playback_info().playback_status == Status.PLAYING
               for session in manager.get_sessions())

def get_current_media() -> str:
    """
    Return the media currently exposed through Windows GSMTC.

    Works with applications such as Spotify and browsers when they expose
    a System Media Transport Controls session.
    """
    if os.name != "nt":
        return tr('brain.error_gsmtc_media_information_is_only_supported_on_windows')

    try:
        import asyncio
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as MediaManager,
        )
    except ImportError:
        return (
            tr('brain.error_windows_media_control_support_is_not_installed_run_pip_ins')
        )

    async def read_media():
        manager = await MediaManager.request_async()

        session = manager.get_current_session()

        if session is None:
            return None

        properties = await session.try_get_media_properties_async()
        playback = session.get_playback_info()
        timeline = session.get_timeline_properties()

        return {
            "source": session.source_app_user_model_id,
            "title": properties.title or None,
            "artist": properties.artist or None,
            "album_title": properties.album_title or None,
            "album_artist": properties.album_artist or None,
            "track_number": properties.track_number or None,
            "playback_status": str(playback.playback_status),
            "position_seconds": (
                timeline.position.total_seconds()
                if timeline is not None
                else None
            ),
            "duration_seconds": (
                timeline.end_time.total_seconds()
                if timeline is not None
                else None
            ),
        }

    try:
        result = asyncio.run(read_media())
    except Exception as error:
        return tr('brain.error_reading_windows_media_session', error=error)

    if result is None:
        return tr('brain.no_active_windows_media_session_was_found')

    return json.dumps(result, ensure_ascii=False, indent=2)


def list_media_sessions() -> str:
    """List every media session currently exposed through Windows GSMTC."""
    if os.name != "nt":
        return tr('brain.error_gsmtc_media_information_is_only_supported_on_windows')

    try:
        import asyncio
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as MediaManager,
        )
    except ImportError:
        return (
            tr('brain.error_windows_media_control_support_is_not_installed_run_pip_ins')
        )

    async def read_sessions():
        manager = await MediaManager.request_async()

        result = []

        for session in manager.get_sessions():
            try:
                properties = await session.try_get_media_properties_async()
                playback = session.get_playback_info()

                result.append({
                    "source": session.source_app_user_model_id,
                    "title": properties.title or None,
                    "artist": properties.artist or None,
                    "album": properties.album_title or None,
                    "playback_status": str(playback.playback_status),
                })

            except Exception as error:
                result.append({
                    "source": session.source_app_user_model_id,
                    "error": str(error),
                })

        return result

    try:
        sessions = asyncio.run(read_sessions())
    except Exception as error:
        return tr('brain.error_reading_windows_media_sessions', error=error)

    if not sessions:
        return tr('brain.no_windows_media_sessions_were_found')

    return json.dumps(sessions, ensure_ascii=False, indent=2)


def resolve_safe_path(path: str) -> Path:
    from .paths import resolve_session_path
    return resolve_session_path(path)

def resolve_entry_path(path: str) -> Path:
    """Resolve a directory entry without following its final symbolic link."""
    from .paths import session_directory
    target = Path(path).expanduser()
    target = target if target.is_absolute() else session_directory() / target
    return target.parent.resolve() / target.name

def _is_arlo_source_path(path: Path) -> bool:
    from src.init.paths import PROJECT_ROOT

    try:
        path.resolve().relative_to(PROJECT_ROOT.resolve())
        return True
    except ValueError:
        return False

def decode_text(data: bytes) -> tuple[str, str]:
    """Decode common Windows text formats and return text plus its encoding."""
    if data.startswith(codecs.BOM_UTF8):
        candidates = ("utf-8-sig",)
    elif data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        candidates = ("utf-16",)
    else:
        candidates = ("utf-8", "cp1252")

    for encoding in candidates:
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        control_characters = sum(
            ord(character) < 32 and character not in "\n\r\t\f\b"
            for character in text
        )
        if control_characters <= max(1, len(text) // 100):
            return text, encoding
    raise UnicodeError(
        tr('brain.file_is_binary_or_uses_an_unsupported_text_encoding_use_the_bina')
    )


def atomic_write_bytes(path: Path, content: bytes) -> None:
    """Replace a file atomically so a failed write does not leave it truncated."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="wb", dir=path.parent, delete=False) as temporary_file:
            temporary_file.write(content)
            temporary_path = Path(temporary_file.name)
        os.replace(temporary_path, path)
    except Exception:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
        raise


def learn_pronunciation(word: str, pronunciation: str) -> str:
    """Learn how a word should be pronounced aloud and remember it permanently."""
    return update_config({"pronunciations": {
        word.strip().casefold(): pronunciation.strip()
    }})

def should_show_working_directory() -> bool:
    """Whether a successful cd has enabled the location in the prompt."""
    from .sessions import active_execution
    identity = active_execution.get()
    return identity is not None and identity.session.show_working_directory


def take_screenshot() -> str:
    """Take a screenshot of the primary monitor and copy it to the clipboard.
    Use when the user explicitly asks to capture the screen, take a screenshot,
    or copy an image of the desktop to the clipboard.
    """
    return request_screenshot()


def empty_recycle_bin() -> str:
    """Empty the recycle bin directory"""
    try:
        winshell.recycle_bin().empty(confirm=False,
        show_progress=False, sound=True)
    except Exception:
        print(tr('brain.error_recycle_bin_is_already_empty'))
