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
import subprocess
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _path(path):
    target = (ROOT / path).resolve()
    relative = target.relative_to(ROOT)
    if any(part in (".git", ".venv", "__pycache__") for part in relative.parts):
        raise ValueError(
            tr('self_code.choose_a_source_file_not_git_metadata_or_the_runtime'))
    return target


def get_repo_lnk() -> str:
    """Open the assistant's public repository in the user's default external browser.
    Use when asked to open the assistant's online repository, not to inspect local code.
    """
    url = "https://github.com/xddigs/arlo"
    try:
        if not webbrowser.open(url, new=2):
            return tr('self_code.error_could_not_open_the_default_browser_repository', url=url)
        return tr('self_code.opened_repository_in_the_default_browser', url=url)
    except Exception as error:
        return tr('self_code.error_opening_repository_repository', error=error, url=url)


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
