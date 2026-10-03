#  Copyright (c) 2026 Diego.
#
#  SPDX-License-Identifier: GPL-3.0-or-later
#
#  This file is part of morgan.
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
"""Qt-free resolution of @file references written in a message."""
import os
import re
from pathlib import Path

FILE_TAG_PATTERN = re.compile(r'(?<!\S)@(?:"([^"\r\n]+)"|([^\s"]+))')
FILE_TAG_QUERY = re.compile(r'(?<!\S)@(?:"([^"\r\n]*)|([^\s"]*))$')
FILE_TAG_TRAILING = ",.;:!?)]}"
FILE_TAG_LIMIT = 50


def _tag_path(base, name):
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        return None
    path = base / name
    return path if os.path.lexists(path) else None


def find_file_tags(text, directory=None):
    base = Path(directory or os.getcwd())
    tags = []
    for match in FILE_TAG_PATTERN.finditer(text):
        if match.group(1) is not None:
            path = _tag_path(base, match.group(1))
            if path is not None:
                tags.append((match.start(), match.end(), match.group(1), path))
            continue
        name = match.group(2)
        while name:
            path = _tag_path(base, name)
            if path is not None:
                tags.append((match.start(), match.start() + 1 + len(name), name, path))
                break
            if name[-1] not in FILE_TAG_TRAILING:
                break
            name = name[:-1]
    return tags


def expand_file_tags(text, directory=None):
    tags = {}
    for _start, _end, name, path in find_file_tags(text, directory):
        tags.setdefault(name, path)
    if not tags:
        return text
    lines = [f"- @{name}: {path} ({'directory' if path.is_dir() else 'file'})"
             for name, path in tags.items()]
    return (text + "\n\nTagged paths from the current working directory "
            "(@name is only a reference; pass the resolved path to tools):\n"
            + "\n".join(lines))
