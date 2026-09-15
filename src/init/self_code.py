"""Access Nora's own checkout independently of the user's working directory."""

import json
import subprocess
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
    """Get the latest git repository of Nora, yourself,
    with a web browser of the user's choice"""
    return "https://github.com/xddigs/nora.git"


def get_nora_repository() -> str:
    """Locate Nora's actual source checkout and report its Git status."""
    from .brain import git_status
    from .config import CONFIG_FILE
    return json.dumps(
        {"repository": str(ROOT), "entrypoint": str(ROOT / "agent.py"),
         "user_config": str(CONFIG_FILE), "git_status": git_status(str(ROOT))},
        ensure_ascii=False)


def list_nora_code(directory: str = ".") -> str:
    """List a directory inside Nora's source checkout without changing cwd."""
    from .brain import list_files
    try:
        return list_files(str(_path(directory)))
    except (OSError, ValueError) as error:
        return f"Error: {error}"


def read_nora_code(path: str) -> str:
    """Read Nora's source using a repository-relative path, e.g. agent.py."""
    from .brain import read_file
    try:
        return read_file(str(_path(path)))
    except (OSError, ValueError) as error:
        return f"Error: {error}"


def edit_nora_code(path: str, old_text: str, new_text: str) -> str:
    """Replace one exact source fragment after reading it. Preserves encoding.

    Refuses ambiguous matches and invalid Python syntax. Changes are saved on
    disk; restart Nora to activate them reliably. Does not commit or push.
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
        return f"Updated {target}. Restart Nora to activate the change; no commit or push performed."
    except (OSError, ValueError, UnicodeError, SyntaxError) as error:
        return f"Error editing Nora code: {error}"


def update_nora_repository() -> str:
    """Pull Nora's configured upstream with fast-forward only, when requested.

    Refuses local changes, including untracked files. Does not restart Nora,
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
            return f"Error checking Nora repository: {status.stderr.strip()}"
        if status.stdout.strip():
            return "Error: Nora has local changes; resolve them before updating.\n" + status.stdout.strip()
        result = run_git(str(ROOT), ["pull", "--ff-only"])
        return result + "\nOnly files on disk were updated if Git succeeded. Restart Nora to load them."
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"Error updating Nora repository: {error}"
