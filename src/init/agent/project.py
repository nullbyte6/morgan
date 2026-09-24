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

import codecs
import hashlib
import stat
import subprocess
from pathlib import Path

from .models import InspectedFile, ProjectContext


MAX_DISCOVERED_FILES = 1024
MAX_FILE_BYTES = 16384


def _git(directory: Path, *arguments: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(directory), *arguments], capture_output=True,
        timeout=10, check=True)
    return result.stdout


def _target(directory: Path, path: str) -> Path:
    relative = Path(path)
    if relative.is_absolute() or relative.drive or ".." in relative.parts:
        raise ValueError("Path must be relative to the inspection directory")
    target = directory
    for part in relative.parts:
        target = target / part
        if target.is_symlink() or target.is_junction():
            raise ValueError("Linked paths are not inspected")
    target = target.resolve(strict=True)
    target.relative_to(directory)
    if not stat.S_ISREG(target.stat().st_mode):
        raise ValueError("Only regular files can be inspected")
    return target


def _repository_root(path: Path) -> Path:
    return Path(_git(path, "rev-parse", "--show-toplevel")
                .decode("utf-8").strip()).resolve(strict=True)


def discover_project(working_directory: str) -> ProjectContext:
    directory = Path(working_directory).expanduser().resolve(strict=True)
    if not directory.is_dir():
        raise ValueError("Inspection requires a working directory")
    context = ProjectContext(working_directory=str(directory))
    try:
        root = _repository_root(directory)
        directory.relative_to(root)
        context.repository_root = str(root)
        repository_roots: dict[Path, Path | None] = {}
        entries = _git(directory, "ls-files", "--cached", "--others",
                       "--exclude-standard", "-z", "--", ".").split(b"\0")
        for entry in sorted(set(entries)):
            if not entry:
                continue
            if len(context.discovered_files) >= MAX_DISCOVERED_FILES:
                context.limitations.append("File inventory limit reached")
                break
            try:
                path = entry.decode("utf-8")
                target = _target(directory, path)
                parent = target.parent
                if parent not in repository_roots:
                    try:
                        repository_roots[parent] = _repository_root(parent)
                    except (OSError, subprocess.SubprocessError):
                        repository_roots[parent] = None
                if repository_roots[parent] != root:
                    continue
            except (OSError, ValueError, subprocess.SubprocessError):
                continue
            context.discovered_files.append(path)
        context.limitations.append(
            "Inventory excludes ignored untracked files, linked paths and submodules")
    except (OSError, ValueError, subprocess.SubprocessError):
        context.limitations.append("Git repository discovery unavailable")
    return context


def inspect_project_files(context: ProjectContext, paths: list[str]) -> ProjectContext:
    if len(paths) > 8 or any(path not in context.discovered_files for path in paths):
        raise ValueError("Inspection selection must use at most eight discovered paths")
    result = context.model_copy(deep=True)
    directory = Path(context.working_directory)
    for path in dict.fromkeys(paths):
        try:
            target = _target(directory, path)
            root = _repository_root(target.parent)
            if str(root) != context.repository_root:
                raise ValueError("File belongs to another repository")
            with target.open("rb") as stream:
                data = stream.read(MAX_FILE_BYTES + 1)
            truncated = len(data) > MAX_FILE_BYTES
            data = data[:MAX_FILE_BYTES]
            if b"\0" in data:
                raise ValueError("Binary content is not inspected")
            content = codecs.getincrementaldecoder("utf-8-sig")().decode(
                data, final=not truncated)
            result.files.append(InspectedFile(
                path=path, content=content, bytes_read=len(data),
                sha256=hashlib.sha256(data).hexdigest(), truncated=truncated))
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            result.limitations.append(f"Could not inspect {path}: {type(error).__name__}")
    return result
