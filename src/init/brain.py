#type: ignore
import base64
import codecs
import ctypes
import importlib
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
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import lru_cache
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from urllib.parse import urlencode, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import unicodedata
import winshell

from .identity import get_assistant

try:
    import winreg
except ImportError:
    winreg = None

from .config import (CONFIG_FILE, HOME_PATH, ensure_storage, load_config)
from .app_cache import cached_app, remember_app, forget_app
from .steam import steam_manager

VERSION = "v1.0.1-alpha"

MODEL_NAME = os.environ.get("NORA_MODEL", load_config().get("model_name"))
OLLAMA_KEEP_ALIVE = os.environ.get("NORA_KEEP_ALIVE",
                                   load_config().get("keep_alive"))
GIT_TIMEOUT_SECONDS = int(os.environ.get("NORA_GIT_TIMEOUT", "120"))
NOMINATIM_BASE_URL = os.environ.get(
    "NORA_GEOCODER_URL", "https://nominatim.openstreetmap.org").rstrip("/")
OSRM_BASE_URL = os.environ.get(
    "NORA_ROUTER_URL", "https://router.project-osrm.org").rstrip("/")
NOMINATIM_MIN_INTERVAL_SECONDS = 1.05
_GEOCODE_CACHE: dict[str, dict[str, object] | None] = {}
_GEOCODE_LOCK = threading.Lock()
NOTES_FILE = HOME_PATH / "note" / f"{datetime.now():%Y-%m-%d_%H-%M-%S_%f}.txt"
APPLICATION_SUFFIXES = (".exe", ".com", ".bat", ".cmd", ".lnk", ".appref-ms")
_APPLICATION_SEARCH_CACHE: dict[str, list[dict[str, str]]] = {}

_SHOW_WORKING_DIRECTORY = False
_LAST_GEOCODE_REQUEST_AT = 0.0


VOICE_NAME = "es_AR-daniela-high"
VOICE_DIR = Path(__file__).resolve().parents[1] / "voices"
VOICE_MODEL = VOICE_DIR / f"{VOICE_NAME}.onnx"


def get_version() -> str:
    """Return the assistant's current version from its application configuration."""
    try:
        config = load_config()
        return config.get("version", VERSION)
    except (OSError, ValueError):
        return VERSION


def update_version(new_version: str) -> str:
    """Update the assistant's version live, preserving all other configuration settings."""
    if not isinstance(new_version, str) or not new_version.strip():
        return "Error updating version: new_version must be a non-empty string"
    new_version = new_version.strip()
    try:
        config = load_config()
        config["version"] = new_version
        config["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        atomic_write_bytes(
            CONFIG_FILE,
            json.dumps(config, indent=2, ensure_ascii=False).encode("utf-8"),
        )
        global VERSION
        VERSION = new_version
        return f"Version updated to {new_version} in config.json"
    except Exception as error:
        return f"Error updating version: {error}"


def refresh() -> str:
    """Reload application modules in memory without restarting the process."""
    try:
        modules_to_reload = [
            "src.init.brain",
            "src.init.tools",
            "src.init.rules",
        ]

        for mod_name in modules_to_reload:
            if mod_name in sys.modules:
                importlib.reload(sys.modules[mod_name])

        return "Modules are reloaded"
    except Exception as error:
        return f"Error at refresh attempt: {error}"


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
    return str(Path.cwd())


def change_directory(path: str = "") -> str:
    """Persistently change the assistant's working directory; empty path reports it.
    Accepts relative or absolute paths, Windows drive paths, quotes, ~ and
    environment variables. Subsequent tools resolve relative paths here.
    """
    global _SHOW_WORKING_DIRECTORY
    try:
        path = path.strip()
        if not path:
            _SHOW_WORKING_DIRECTORY = True
            return get_working_directory()
        if len(path) >= 2 and path[0] == path[-1] and path[0] in "\"'":
            path = path[1:-1]
        if not path:
            return "Error: directory path is empty"
        destination = resolve_safe_path(os.path.expandvars(path))
        os.chdir(destination)
        _SHOW_WORKING_DIRECTORY = True
        return f"Current directory: {get_working_directory()}"
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
        return "Error: region must be a string"
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
                return f"Error: unknown timezone or missing tzdata: {region}"
            place = geocode_city(region)
            if place is None:
                return f"Error: location not found: {region}"
            zone_name = _timezone_finder().timezone_at(
                lat=place["latitude"], lng=place["longitude"])
            if zone_name is None:
                return f"Error: timezone not found for: {region}"
            zone = ZoneInfo(zone_name)
            place_name = place["name"]
        current = datetime.now(zone)
        return f"{place_name}: {current:%Y-%m-%d %H:%M:%S} ({zone.key}, UTC{current:%z})"
    except ImportError:
        return "Error: timezone dependencies missing; run pip install -r requirements.txt"
    except Exception as error:
        return f"Error getting current time for {region}: {error}"


def calculate(expression: str) -> str:
    if not set(expression) <= set("0123456789+-*/(). "):
        return "Error: only numbers and arithmetic operators are allowed"
    try:
        return str(eval(expression, {"__builtins__": {}}, {}))
    except Exception as error:
        return f"Error: {error}"


def save_note(note: str) -> str:
    ensure_storage()
    with NOTES_FILE.open("a", encoding="utf-8") as file:
        file.write(f"{note}\n")
    return "Note saved"


def read_notes() -> str:
    ensure_storage()
    notes = sorted((HOME_PATH / "note").glob("*.txt"))
    return "\n\n".join(
        f"{path.name}\n{path.read_text(encoding='utf-8')}" for path in
        notes) if notes else "No notes saved yet"


def list_files(path: str = ".") -> str:
    try:
        folder = resolve_safe_path(path)
        if not folder.exists():
            return f"Directory does not exist: {folder}"
        if not folder.is_dir():
            return f"Not a directory: {folder}"
        items = []
        for item in folder.iterdir():
            kind = "DIR" if item.is_dir() else "FILE"
            items.append(f"[{kind}] {item.name}")
        return "\n".join(items) if items else "Directory is empty"
    except Exception as error:
        return f"Error: {error}"


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
        return f"Error searching directories: {error}"


def create_directory(path: str, parents: bool = True) -> str:
    """Create a directory; optionally create all missing parent directories."""
    try:
        directory_path = resolve_safe_path(path)
        if directory_path.exists():
            if directory_path.is_dir():
                return f"Directory already exists: {directory_path}"
            return f"A file already exists at: {directory_path}"
        directory_path.mkdir(parents=parents, exist_ok=False)
        return f"Directory created: {directory_path}"
    except Exception as error:
        return f"Error: {error}"


def rename_directory(path: str, new_name: str) -> str:
    """Rename a directory in place; new_name must be a name, not another path."""
    try:
        directory_path = resolve_entry_path(path)
        if not directory_path.exists():
            return f"Directory does not exist: {directory_path}"
        if not directory_path.is_dir():
            return f"Not a directory: {directory_path}"
        if (not new_name.strip() or new_name in (".", "..")
                or Path(new_name).name != new_name):
            return f"Invalid directory name: {new_name}"
        destination = directory_path.with_name(new_name)
        if destination.exists() or destination.is_symlink():
            return f"Destination already exists: {destination}"
        directory_path.rename(destination)
        return f"Directory renamed: {directory_path} -> {destination}"
    except Exception as error:
        return f"Error: {error}"


def delete_directory(path: str, recursive: bool = False) -> str:
    """Delete a directory; recursive must be true to remove any contents."""
    try:
        directory_path = resolve_entry_path(path)
        if not directory_path.exists() and not directory_path.is_symlink():
            return f"Directory does not exist: {directory_path}"
        if not directory_path.is_dir():
            return f"Not a directory: {directory_path}"
        if directory_path == Path(directory_path.anchor):
            return f"Refusing to delete a filesystem root: {directory_path}"

        is_junction = (hasattr(directory_path, "is_junction")
                       and directory_path.is_junction())
        if directory_path.is_symlink():
            directory_path.unlink()
        elif is_junction:
            directory_path.rmdir()
        elif recursive:
            shutil.rmtree(directory_path)
        elif any(directory_path.iterdir()):
            return (f"Directory is not empty: {directory_path}. "
                    "Recursive deletion was not requested")
        else:
            directory_path.rmdir()
        return f"Directory deleted: {directory_path}"
    except Exception as error:
        return f"Error: {error}"


def read_file(path: str) -> str:
    """Read a text file while detecting UTF-8, UTF-16 or Windows-1252."""
    try:
        file_path = resolve_safe_path(path)
        if not file_path.exists():
            return f"File does not exist: {file_path}"
        if not file_path.is_file():
            return f"Not a file: {file_path}"
        content, _ = decode_text(file_path.read_bytes())
        return content
    except Exception as error:
        return f"Error: {error}"


def create_file(path: str, content: str = "", encoding: str = "utf-8") -> str:
    """Create a new text file and fail rather than overwrite an existing file."""
    try:
        file_path = resolve_safe_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with file_path.open("x", encoding=encoding) as file:
            file.write(content)
        return f"File created: {file_path}"
    except FileExistsError:
        return f"File already exists: {resolve_safe_path(path)}"
    except (LookupError, OSError) as error:
        return f"Error: {error}"


def write_file(path: str, content: str) -> str:
    """Create or completely overwrite a UTF-8 text file."""
    try:
        file_path = resolve_safe_path(path)
        atomic_write_bytes(file_path, content.encode("utf-8"))
        return f"File written: {file_path}"
    except Exception as error:
        return f"Error: {error}"


def edit_file(path: str, content: str) -> str:
    """Replace all text in an existing file while preserving its encoding."""
    try:
        file_path = resolve_safe_path(path)
        if not file_path.exists():
            return f"File does not exist: {file_path}"
        if not file_path.is_file():
            return f"Not a file: {file_path}"
        _, encoding = decode_text(file_path.read_bytes())
        atomic_write_bytes(file_path, content.encode(encoding))
        return f"File edited: {file_path}"
    except Exception as error:
        return f"Error: {error}"


def append_file(path: str, content: str) -> str:
    """Append text to a file, preserving its existing text encoding."""
    try:
        file_path = resolve_safe_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        encoding = "utf-8"
        if file_path.exists():
            if not file_path.is_file():
                return f"Not a file: {file_path}"
            _, encoding = decode_text(file_path.read_bytes())
        with file_path.open("a", encoding=encoding) as file:
            file.write(content)
        return f"Content appended to: {file_path}"
    except Exception as error:
        return f"Error: {error}"


def replace_in_file(path: str, old_text: str, new_text: str) -> str:
    """Replace matching text in an existing file without changing its encoding."""
    try:
        file_path = resolve_safe_path(path)
        if not file_path.exists():
            return f"File does not exist: {file_path}"
        if not file_path.is_file():
            return f"Not a file: {file_path}"
        content, encoding = decode_text(file_path.read_bytes())
        if old_text not in content:
            return "Text to replace was not found"
        occurrences = content.count(old_text)
        updated_content = content.replace(old_text, new_text)
        atomic_write_bytes(file_path, updated_content.encode(encoding))
        return f"Replaced {occurrences} occurrence(s) in {file_path}"
    except Exception as error:
        return f"Error: {error}"


def run_git(repository: str, arguments: list[str]) -> str:
    """Run one internally selected Git operation without invoking a shell."""
    try:
        repository_path = resolve_safe_path(repository)
        if not repository_path.exists():
            return f"Error: repository path does not exist: {repository_path}"
        if not repository_path.is_dir():
            return f"Error: repository path is not a directory: {repository_path}"
        if shutil.which("git") is None:
            return "Error: Git is not installed or is not available on PATH"

        environment = os.environ.copy()
        environment["GIT_TERMINAL_PROMPT"] = "0"
        result = subprocess.run(
            ["git", "-C", str(repository_path), "--no-pager", *arguments],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=GIT_TIMEOUT_SECONDS,
            env=environment,
        )
        output = "\n".join(
            part.strip() for part in (result.stdout, result.stderr) if
            part.strip()
        )
        if result.returncode != 0:
            detail = output or "Git did not provide an error message"
            return f"Error: git exited with code {result.returncode}: {detail}"
        return output or "Git command completed successfully"
    except subprocess.TimeoutExpired:
        return f"Error: Git command timed out after {GIT_TIMEOUT_SECONDS} seconds"
    except OSError as error:
        return f"Error: {error}"


def valid_git_name(value: str, label: str) -> str | None:
    """Reject empty or option-like Git names before passing them to Git."""
    if not value or value.startswith("-") or "\x00" in value:
        return f"Error: invalid Git {label}: {value!r}"
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
            return f"Error: invalid Git branch: {value!r}"
    return None


def git_status(repository: str = ".") -> str:
    """Show the current branch and concise working-tree status for a repository."""
    return run_git(repository, ["status", "--short", "--branch"])


def git_diff(repository: str = ".", staged: bool = False,
             path: str = "") -> str:
    """Show unstaged changes, or staged changes when staged is true."""
    arguments = ["diff", "--no-ext-diff"]
    if staged:
        arguments.append("--staged")
    if path:
        arguments.extend(["--", path])
    result = run_git(repository, arguments)
    if result == "Git command completed successfully":
        return "No differences found"
    return result


def git_add(paths: list[str], repository: str = ".") -> str:
    """Stage the exact files or pathspecs supplied in paths for a later commit."""
    if not paths or any(not path or "\x00" in path for path in paths):
        return "Error: provide at least one valid path to stage"
    return run_git(repository, ["add", "--", *paths])


def git_commit(message: str, repository: str = ".") -> str:
    """Create a commit from staged changes with the supplied commit message."""
    if not message.strip() or "\x00" in message:
        return "Error: commit message cannot be empty"
    return run_git(repository, ["commit", "-m", message])


def git_fetch(repository: str = ".", remote: str = "",
              prune: bool = False) -> str:
    """Download remote refs without changing local files or the current branch."""
    arguments = ["fetch"]
    if prune:
        arguments.append("--prune")
    if remote:
        error = valid_git_name(remote, "remote")
        if error:
            return error
        arguments.append(remote)
    return run_git(repository, arguments)


def git_pull(repository: str = ".", remote: str = "", branch: str = "",
             rebase: bool = False) -> str:
    """Fetch and integrate a remote branch into the checked-out local branch."""
    if branch and not remote:
        return "Error: a remote is required when a branch is supplied"
    arguments = ["pull"]
    if rebase:
        arguments.append("--rebase")
    for value, label in ((remote, "remote"), (branch, "branch")):
        if value:
            error = valid_git_name(value, label)
            if error:
                return error
            arguments.append(value)
    return run_git(repository, arguments)


def git_push(repository: str = ".", remote: str = "", branch: str = "",
             set_upstream: bool = False) -> str:
    """Publish commits to a configured remote, optionally setting the upstream."""
    if branch and not remote:
        return "Error: a remote is required when a branch is supplied"
    if set_upstream and not remote:
        return "Error: a remote is required when setting the upstream"
    arguments = ["push"]
    if set_upstream:
        arguments.append("--set-upstream")
    for value, label in ((remote, "remote"), (branch, "branch")):
        if value:
            error = valid_git_name(value, label)
            if error:
                return error
            arguments.append(value)
    return run_git(repository, arguments)


def git_log(repository: str = ".", max_count: int = 10) -> str:
    """Show a concise recent commit history."""
    if isinstance(max_count, bool) or not 1 <= max_count <= 100:
        return "Error: max_count must be between 1 and 100"
    return run_git(
        repository,
        ["log", f"--max-count={max_count}", "--oneline", "--decorate"],
    )


def git_list_branches(repository: str = ".",
                      include_remote: bool = False) -> str:
    """List local branches and, when requested, remote-tracking branches."""
    arguments = ["branch"]
    if include_remote:
        arguments.append("--all")
    return run_git(repository, arguments)


def git_switch(branch: str, repository: str = ".",
               create: bool = False) -> str:
    """Switch branches, optionally creating the named branch first."""
    error = valid_git_name(branch, "branch")
    if error:
        return error
    arguments = ["switch"]
    if create:
        arguments.append("--create")
    arguments.append(branch)
    return run_git(repository, arguments)


def read_binary_file(path: str) -> str:
    """Read any binary file and return its bytes encoded as Base64."""
    try:
        file_path = resolve_safe_path(path)
        if not file_path.exists():
            return f"File does not exist: {file_path}"
        if not file_path.is_file():
            return f"Not a file: {file_path}"
        encoded = base64.b64encode(file_path.read_bytes()).decode("ascii")
        return encoded
    except Exception as error:
        return f"Error: {error}"


def write_binary_file(path: str, base64_content: str,
                      overwrite: bool = False) -> str:
    """Create a binary file from Base64; set overwrite only for an existing file."""
    try:
        file_path = resolve_safe_path(path)
        already_exists = file_path.exists()
        if already_exists and not overwrite:
            return f"File already exists: {file_path}"
        content = base64.b64decode(base64_content, validate=True)
        atomic_write_bytes(file_path, content)
        action = "edited" if already_exists else "created"
        return f"Binary file {action}: {file_path}"
    except (ValueError, OSError) as error:
        return f"Error: {error}"


def delete_file(path: str) -> str:
    """Permanently delete one file or symbolic link, never a directory."""
    try:
        file_path = resolve_entry_path(path)
        if not file_path.exists() and not file_path.is_symlink():
            return f"File does not exist: {file_path}"
        if file_path.is_dir() and not file_path.is_symlink():
            return f"Refusing to delete a directory: {file_path}"
        file_path.unlink()
        return f"File deleted: {file_path}"
    except Exception as error:
        return f"Error: {error}"


def open_file(path: str) -> str:
    try:
        target = resolve_safe_path(path)
        if not target.exists():
            return f"Path does not exist: {target}"
        if os.name == "nt":
            os.startfile(target)
        elif os.name == "posix":
            opener = "open" if shutil.which("open") else "xdg-open"
            subprocess.Popen([opener, str(target)])
        else:
            return "Unsupported operating system"
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
                    "Elige la ruta completa de la carpeta que quieres abrir."
                    if matches else "No se encontraron carpetas en la búsqueda realizada.")
                return json.dumps(result, ensure_ascii=False)
            target = Path(matches[0])
        else:
            target = resolve_directory(path)
        if not target.is_dir():
            return f"Error: directory does not exist or is not a folder: {target}"
        opened = open_file(str(target))
        if target.name and opened.startswith("Opened:"):
            remember_folders(target.name, [str(target)], complete=True)
        return opened
    except Exception as error:
        return f"Error opening directory: {error}"


def open_browser(url: str) -> str:
    try:
        if "://" not in url:
            url = "https://" + url
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return "Error: only HTTP and HTTPS URLs are allowed"
        webbrowser.open(url)
        return f"Opened browser: {url}"
    except Exception as error:
        return f"Error: {error}"


def search_web(query: str, region: str = "es-es", max_results: int = 6) -> str:
    """Search the web internally, prioritizing Google, without opening a browser."""
    query = query.strip()
    if not query:
        return "Error: search query is empty"
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
            return f"No web results found for: {query}"
        formatted_results = []
        for index, result in enumerate(results, start=1):
            formatted_results.append(
                f"[{index}] {result.get('title', 'Untitled')}\n"
                f"URL: {result.get('href', '')}\n"
                f"Snippet: {result.get('body', '')}"
            )
        return "\n\n".join(formatted_results)
    except Exception as error:
        return f"Error searching the web: {error}"


def read_web_page(url: str, max_characters: int = 12_000) -> str:
    """Fetch readable page text internally without launching a browser."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return "Error: a valid HTTP or HTTPS URL is required"
    if not 1_000 <= max_characters <= 30_000:
        return "Error: max_characters must be between 1000 and 30000"
    try:
        from ddgs import DDGS

        result = DDGS(timeout=15).extract(url, fmt="text_plain")
        content = result.get("content", "")
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="replace")
        content = str(content).strip()
        if not content:
            return f"No readable content found at: {url}"
        if len(content) > max_characters:
            content = content[:max_characters] + "\n[Content truncated]"
        return f"Source URL: {url}\n\n{content}"
    except Exception as error:
        return f"Error reading web page: {error}"


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
            return f"Error: location not found: {origin}"
        if destination_place is None:
            return f"Error: location not found: {destination}"

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
                    "OSRM returned status "
                    f"{route_data.get('code', 'unknown')}"
                )
        except Exception as error:
            route_error = f"Driving route could not be verified: {error}"

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
                    "Approximate geodesic distance between the resolved coordinates."
                ),
                "driving_route": (
                    "Calculated road-route length; it can vary by route and conditions."
                ),
            },
            "sources": [
                f"{NOMINATIM_BASE_URL}/ — © OpenStreetMap contributors (ODbL)",
                f"{OSRM_BASE_URL}/ — data © OpenStreetMap contributors",
            ],
        }
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as error:
        return f"Error calculating city distance: {error}"


def kill_process(process: str, force: bool = False,
                 include_children: bool = False) -> str:
    """End a Windows process by exact PID or image name."""
    if os.name != "nt":
        return "Error: kill_process is only supported on Windows"

    target = process.strip()
    if not target:
        return "Error: process PID or image name is required"

    command = ["taskkill.exe"]
    if target.isdecimal():
        process_id = int(target)
        if process_id <= 4:
            return f"Refusing to terminate a critical system PID: {process_id}"
        if process_id == os.getpid():
            return f"Refusing to terminate {get_assistant().name}'s own PID: {process_id}"
        command.extend(["/PID", str(process_id)])
        description = f"PID {process_id}"
    else:
        forbidden_characters = set('<>:"/\\|?*')
        if forbidden_characters.intersection(target):
            return f"Error: invalid process image name: {target}"
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
            return f"Refusing to terminate a critical or current process: {image_name}"
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
            return f"Error terminating {description}: {detail or 'taskkill failed'}"
        return f"Process terminated: {description}"
    except OSError as error:
        return f"Error: {error}"


def shutdown_computer(delay_seconds: int) -> str:
    """Schedule a Windows shutdown after an exact number of seconds."""
    if os.name != "nt":
        return "Error: shutdown_computer is only supported on Windows"
    if isinstance(delay_seconds, bool) or not isinstance(delay_seconds, int):
        return "Error: delay_seconds must be an integer"
    if not 0 <= delay_seconds <= 315_360_000:
        return "Error: delay_seconds must be between 0 and 315360000"

    try:
        result = subprocess.run(
            [
                "shutdown.exe",
                "/s",
                "/t",
                str(delay_seconds),
                "/c",
                f"Shutdown scheduled by {get_assistant().name}",
            ],
            capture_output=True,
            text=True,
            errors="replace",
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            return f"Error scheduling shutdown: {detail or 'shutdown failed'}"
        return f"Computer shutdown scheduled in {delay_seconds} second(s)"
    except OSError as error:
        return f"Error: {error}"


def cancel_shutdown() -> str:
    """Cancel a shutdown that is currently pending on Windows."""
    if os.name != "nt":
        return "Error: cancel_shutdown is only supported on Windows"
    try:
        result = subprocess.run(
            ["shutdown.exe", "/a"],
            capture_output=True,
            text=True,
            errors="replace",
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            return f"Error cancelling shutdown: {detail or 'no shutdown is pending'}"
        return "Pending computer shutdown cancelled"
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
        return "No applications found"
    return "\n".join(sorted(app["Name"] for app in apps))


def list_open_applications() -> str:
    """List current taskbar-style windows, including minimized applications.

    Use for 'what apps are open' or taskbar requests. Excludes background-only
    processes, tray-only apps and installed/pinned apps without an open window.
    Enumerates standard visible windows on the current desktop; custom Shell
    taskbar registration or virtual-desktop settings may differ.
    """
    if os.name != "nt":
        return "Error: listing open applications is only supported on Windows"
    try:
        from src.init.windows import get_open_windows

        return json.dumps({"open_windows": get_open_windows()},
                          ensure_ascii=False, indent=2)
    except Exception as error:
        return f"Error listing open applications: {error}"


def _launch_application(app):
    if app["Source"] == "registered":
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app['AppID']}"],
                         creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        os.startfile(app["Path"])


def launch_steam_game(game: str) -> str:
    """Launch an installed Steam game by its name."""
    return steam_manager.launch(game)


def list_steam_games() -> str:
    """List all installed Steam games."""
    games = steam_manager.games()
    if not games:
        return "No Steam games found"

    return "\n".join(
        sorted((str(game) for game in games), key=str.casefold)
    )


def find_steam_game(game: str) -> str:
    """Find an installed Steam game by its name."""
    if steam_manager.find_game(game):
        return f"Steam game found: {steam_manager.find_game(game)}"
    return None


def open_application(application: str) -> str:
    """Open an app, consulting persistent apps.json before expensive discovery."""
    from src.init.folders import FOLDER_ALIASES

    raw_application = application.strip().strip('"').strip("'")
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
                _launch_application(app)
                remember_app(normalize_application_name(path_candidate.stem), app)
                return f"Opened application: {path_candidate.stem}"
            except Exception as error:
                return f"Error opening application path {raw_application}: {error}"
        return f"Application path not found or is not an executable file: {raw_application}"

    query = raw_application.casefold()
    normalized_query = normalize_application_name(query)
    if not normalized_query:
        return "Application name is empty"

    app = cached_app(normalized_query)
    if app:
        try:
            _launch_application(app)
            return f"Opened application: {app['Name']}"
        except Exception:
            forget_app(normalized_query)
    _APPLICATION_SEARCH_CACHE.pop(normalized_query, None)

    registered = [
        {**app, "Source": "registered" if app.get("AppID") else "file"}
        for app in get_applications()
        if normalized_query in normalize_application_name(app["Name"])
    ]
    matches = registered + find_applications_on_all_drives(application)
    if not matches:
        return f"Application not found: {application}"

    app = min(matches, key=lambda candidate:
    application_rank(candidate, normalized_query))
    try:
        _launch_application(app)
        saved = remember_app(normalized_query, app)
        note = "" if saved else " (could not update apps.json cache)"
        return f"Opened application: {app['Name']}{note}"
    except Exception as error:
        return f"Error: {error}"


def identify_playing_song(seconds: int = 8) -> str:
    """Listen to the computer's current output audio and identify the song."""
    if os.name != "nt":
        return "Error: system audio recognition is currently only supported on Windows"

    if not 5 <= seconds <= 20:
        return "Error: seconds must be between 5 and 20"

    try:
        import asyncio
        import numpy as np
        import soundcard as sc
        from shazamio import Shazam
    except ImportError:
        return (
            "Error: music recognition dependencies are not installed. "
            "Run: pip install shazamio soundcard numpy"
        )

    speaker = sc.default_speaker()

    if speaker is None:
        return "Error: no default audio output device was found"
    loopbacks = sc.all_microphones(include_loopback=True)

    loopback = next(
        (
            microphone
            for microphone in loopbacks
            if speaker.name.casefold() in microphone.name.casefold()
               or microphone.name.casefold() in speaker.name.casefold()
        ),
        None,
    )

    if loopback is None:
        return f"Error: no loopback device found for: {speaker.name}"

    sample_rate = 44100
    frames = sample_rate * seconds

    try:
        with loopback.recorder(samplerate=sample_rate) as recorder:
            audio = recorder.record(numframes=frames)
    except Exception as error:
        return f"Error capturing system audio: {error}"

    if audio.size == 0:
        return "No system audio was captured"

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
            return "No song could be identified from the current system audio"

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
        return f"Error identifying song: {error}"

    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def get_current_media() -> str:
    """
    Return the media currently exposed through Windows GSMTC.

    Works with applications such as Spotify and browsers when they expose
    a System Media Transport Controls session.
    """
    if os.name != "nt":
        return "Error: GSMTC media information is only supported on Windows"

    try:
        import asyncio
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as MediaManager,
        )
    except ImportError:
        return (
            "Error: Windows media control support is not installed. "
            "Run: pip install winrt-Windows.Media.Control"
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
        return f"Error reading Windows media session: {error}"

    if result is None:
        return "No active Windows media session was found"

    return json.dumps(result, ensure_ascii=False, indent=2)


def list_media_sessions() -> str:
    """List every media session currently exposed through Windows GSMTC."""
    if os.name != "nt":
        return "Error: GSMTC media information is only supported on Windows"

    try:
        import asyncio
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as MediaManager,
        )
    except ImportError:
        return (
            "Error: Windows media control support is not installed. "
            "Run: pip install winrt-Windows.Media.Control"
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
        return f"Error reading Windows media sessions: {error}"

    if not sessions:
        return "No Windows media sessions were found"

    return json.dumps(sessions, ensure_ascii=False, indent=2)


def resolve_safe_path(path: str) -> Path:
    return Path(path).expanduser().resolve()


def resolve_entry_path(path: str) -> Path:
    """Resolve a directory entry without following its final symbolic link."""
    return Path(os.path.abspath(Path(path).expanduser()))


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
        "File is binary or uses an unsupported text encoding; use the binary tools"
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


def should_show_working_directory() -> bool:
    """Whether a successful cd has enabled the location in the prompt."""
    return _SHOW_WORKING_DIRECTORY

def empty_recycle_bin() -> str:
    """Empty the recycle bin directory"""
    try:
        winshell.recycle_bin().empty(confirm=False,
        show_progress=False, sound=True)
    except Exception:
        print("Error: Recycle Bin is already empty!")
