from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


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

    executable = shutil.which("pyvim")
    if executable is None:
        return (
            "PyVim is not installed or is not available on PATH. "
            "Install it with: pip install pyvim"
        )

    try:
        result = subprocess.run([
            executable,
            str(requested),
        ])

        if result.returncode != 0:
            return f"PyVim exited with code {result.returncode}"
        return f"Editor closed: {requested}"

    except OSError as error:
        return f"Could not launch PyVim: {error}"