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
"""Read uncommitted Git changes for automatic task-completion workspaces."""

import os
import subprocess

from ..lang import tr


def _run_git(repo_path: str, arguments: list[str]) -> subprocess.CompletedProcess:
    """Run Git with literal paths and predictable text output."""
    return subprocess.run(
        ['git', '--no-pager', '--literal-pathspecs', *arguments],
        cwd=repo_path,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='surrogateescape',
        check=False,
        timeout=10
    )


def _parse_status(output: str) -> list[tuple[str, str, str | None]]:
    """Read NUL-delimited porcelain records, including rename source paths."""
    entries = []
    records = iter(output.split('\0'))
    for record in records:
        if len(record) < 4:
            continue
        status = record[:2]
        file_path = record[3:]
        source_path = next(records, None) if 'R' in status or 'C' in status else None
        entries.append((status, file_path, source_path))
    return entries


def get_git_patch(repo_path: str) -> str:
    """Read a snapshot of every uncommitted change, or nothing for clean directories."""
    try:
        status = _run_git(repo_path, ['status', '--porcelain=v1', '-z', '--untracked-files=all'])
        if status.returncode != 0 or not status.stdout:
            return ''
        root = _run_git(repo_path, ['rev-parse', '--show-toplevel'])
        if root.returncode != 0:
            return ''
        repository = root.stdout.rstrip('\r\n')
        options = ['--no-color', '--no-ext-diff', '--no-textconv', '--unified=3']
        patches = []
        for cached, title in ((['--cached'], 'git_workspace.staged'), ([], 'git_workspace.unstaged')):
            result = _run_git(repository, ['diff', *cached, *options])
            if result.returncode != 0:
                return ''
            if result.stdout:
                patches.append(tr(title) + '\n' + result.stdout)
        for code, path, _source in _parse_status(status.stdout):
            if code == '??':
                result = _run_git(repository, ['diff', '--no-index', *options, '--', os.devnull, path])
                if result.returncode not in (0, 1):
                    return ''
                patches.append(tr('git_workspace.untracked', path=path) + '\n' + result.stdout)
        return '\n'.join(patches) or status.stdout.replace('\0', '\n')
    except (OSError, subprocess.SubprocessError):
        return ''
