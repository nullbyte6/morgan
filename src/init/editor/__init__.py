from __future__ import annotations

import subprocess
from pathlib import Path

from agent import Assistant


def open_in_editor(path: str) -> str:
    """Open an existing text file interactively with PyVim.
    Use this when the user explicitly wants to manually edit a file.
    """
    from src.init.brain import get_working_directory

    requested = Path(path).expanduser()
    if not requested.is_absolute():
        requested = Path(get_working_directory()) / requested

    requested = requested.resolve()
    if not requested.exists():
        return f"File not found: {requested}"

    if not requested.is_file():
        return f"Not a file: {requested}"

    try:
        with Assistant().suspend_terminal():
            subprocess.run(["nvim", str(path)])
        return f"Editor closed: {path}"

    except OSError as error:
        return f"Could not launch Neovim: {error}"