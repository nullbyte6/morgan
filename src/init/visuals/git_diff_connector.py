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
"""Connect the Git Diff panel to repository changes and status information."""

import os
import subprocess


def _run_git(repo_path: str, arguments: list[str]) -> subprocess.CompletedProcess:
    """Run Git with literal paths and predictable text output."""
    return subprocess.run(
        ['git', '--literal-pathspecs', *arguments],
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


def _parse_diff(output: str) -> list[dict]:
    """Extract changed and context lines without removing source whitespace."""
    lines = []
    in_hunk = False
    for line in output.split('\n'):
        if line.startswith('diff '):
            in_hunk = False
        elif line.startswith('@@'):
            in_hunk = True
        elif in_hunk:
            if line.startswith('+'):
                lines.append({'type': 'added', 'text': line[1:]})
            elif line.startswith('-'):
                lines.append({'type': 'deleted', 'text': line[1:]})
            elif line.startswith(' '):
                lines.append({'type': 'context', 'text': line[1:]})
            elif line.startswith('\\'):
                lines.append({'type': 'context', 'text': line})
    return lines


def get_git_diff(repo_path: str) -> list[dict]:
    """Return file diffs for staged, unstaged, and untracked changes.

    Each entry contains the file path, a lowercase Git status code, and
    added, deleted, or context lines. Unavailable repositories return no entries.
    """
    diffs = []
    try:
        result = _run_git(repo_path, ['status', '--porcelain=v1', '-z', '--untracked-files=all'])
        if result.returncode != 0:
            return diffs

        for status, file_path, source_path in _parse_status(result.stdout):
            lines = []
            if status == '??':
                diff_result = _run_git(repo_path, [
                    'diff', '--no-index', '--no-color', '--no-ext-diff', '--no-textconv',
                    '--unified=3', '--', os.devnull, file_path
                ])
                if diff_result.returncode not in (0, 1):
                    continue
                lines.extend(_parse_diff(diff_result.stdout))
                status_code = 'a'
            else:
                paths = [file_path] if source_path is None else [source_path, file_path]
                for column, cached in ((0, ['--cached']), (1, [])):
                    if status[column] not in 'MADRCUT':
                        continue
                    diff_result = _run_git(repo_path, [
                        'diff', *cached, '--no-color', '--no-ext-diff', '--no-textconv',
                        '--unified=3', '--', *paths
                    ])
                    if diff_result.returncode == 0:
                        lines.extend(_parse_diff(diff_result.stdout))
                status_code = (status[1] if status[1] != ' ' else status[0]).lower()

            diffs.append({'file': file_path, 'status': status_code, 'lines': lines})
    except (OSError, subprocess.SubprocessError):
        pass
    return diffs


def get_git_status(repo_path: str) -> dict:
    """Return repository validity and modified, added, and deleted file paths.

    Both index and working tree changes are included. Clean repositories are
    valid, and untracked files are listed as added files.
    """
    status = {
        'is_repo': False,
        'modified_files': [],
        'added_files': [],
        'deleted_files': []
    }
    try:
        result = _run_git(repo_path, ['status', '--porcelain=v1', '-z', '--untracked-files=all'])
        if result.returncode != 0:
            return status
        status['is_repo'] = True
        for file_status, file_path, source_path in _parse_status(result.stdout):
            if file_status == '??' or 'A' in file_status or 'C' in file_status:
                status['added_files'].append(file_path)
            if 'D' in file_status:
                status['deleted_files'].append(file_path)
            if any(code in file_status for code in 'MRTU'):
                status['modified_files'].append(file_path)
    except (OSError, subprocess.SubprocessError):
        pass
    return status
