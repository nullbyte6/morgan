"""Access the assistant's own checkout independently of the user's working directory."""

from .identity import get_assistant


import json
import subprocess
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _path(path):
    target = (ROOT / path).resolve()
    relative = target.relative_to(ROOT)
    if any(part in (".git", ".venv", "__pycache__") for part in relative.parts):
        raise ValueError(
            "Choose a source file, not Git metadata or the runtime")
    return target


def get_repo_lnk() -> str:
    """Open the assistant's public repository in the user's default external browser.
    Use when asked to open the assistant's online repository, not to inspect local code.
    """
    url = "https://github.com/xddigs/arlo"
    try:
        if not webbrowser.open(url, new=2):
            return f"Error: could not open the default browser. Repository: {url}"
        return f"Opened repository in the default browser: {url}"
    except Exception as error:
        return f"Error opening repository: {error}. Repository: {url}"


def get_repo() -> str:
    """Locate the assistant's actual source checkout and report its Git status."""
    from .brain import git_status
    from .config import CONFIG_FILE
    return json.dumps(
        {"repository": str(ROOT), "entrypoint": str(ROOT / "agent.py"),
         "user_config": str(CONFIG_FILE), "git_status": git_status(str(ROOT))},
        ensure_ascii=False)


def list_code(directory: str = ".") -> str:
    """List a directory inside the assistant's source checkout without changing cwd."""
    from .brain import list_files
    try:
        return list_files(str(_path(directory)))
    except (OSError, ValueError) as error:
        return f"Error: {error}"


def read_code(path: str) -> str:
    """Read the assistant's source using a repository-relative path, e.g. agent.py."""
    from .brain import read_file
    try:
        return read_file(str(_path(path)))
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
            return "Error: old_text must match exactly once; read the file and use a unique fragment"
        updated = content.replace(old_text, new_text, 1)
        if target.suffix.lower() == ".py":
            compile(updated, str(target), "exec")
        atomic_write_bytes(target, updated.encode(encoding))
        return f"Updated {target}. Restart {get_assistant().name} to activate the change; no commit or push performed."
    except (OSError, ValueError, UnicodeError, SyntaxError) as error:
        return f"Error editing {get_assistant().name} code: {error}"


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
            return f"Error checking {get_assistant().name} repository: {status.stderr.strip()}"
        if status.stdout.strip():
            return f"Error: {get_assistant().name} has local changes; resolve them before updating.\n" + status.stdout.strip()
        result = run_git(str(ROOT), ["pull", "--ff-only"])
        return result + f"\nOnly files on disk were updated if Git succeeded. Restart {get_assistant().name} to load them."
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"Error updating {get_assistant().name} repository: {error}"
