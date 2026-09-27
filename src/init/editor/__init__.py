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
from __future__ import annotations
from src.init.lang import tr

import subprocess
from pathlib import Path

from src.init.identity import get_assistant


def open_in_editor(path: str) -> str:
    """Open an existing text file interactively with PyVim/Neovim
    Use this when the user explicitly wants to manually edit a file.
    """
    from src.init.brain import get_working_directory

    requested = Path(path).expanduser()
    if not requested.is_absolute():
        requested = Path(get_working_directory()) / requested

    requested = requested.resolve()
    if not requested.exists():
        return tr('editor.file_not_found', requested=requested)

    if not requested.is_file():
        return tr('editor.not_a_file', requested=requested)

    try:
        with get_assistant().suspend_terminal():
            subprocess.run(["nvim", str(requested)], cwd=get_working_directory())
        return tr('editor.editor_closed', path=path)

    except OSError as error:
        return tr('editor.could_not_launch_neovim', error=error)
