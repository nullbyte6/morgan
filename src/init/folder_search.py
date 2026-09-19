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
"""Disk-wide directory discovery and a persistent, ambiguity-preserving cache."""

from src.init.lang import tr
from collections import deque
import ctypes
import json
import os
from pathlib import Path
import tempfile
import threading
import time

from .config import HOME_PATH
from .folders import FOLDER_ALIASES, resolve_directory

FOLDERS_FILE = HOME_PATH / "json" / "folders.json"
_lock = threading.RLock()


def _read():
    if not FOLDERS_FILE.exists():
        return {}
    data = json.loads(FOLDERS_FILE.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(tr('folder_search.folders_json_must_contain_an_object'))
    return data


def _write(data):
    temporary = None
    try:
        FOLDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                         dir=FOLDERS_FILE.parent, delete=False) as file:
            temporary = Path(file.name)
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")
        os.replace(temporary, FOLDERS_FILE)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def cached_folders(name):
    with _lock:
        try:
            data = _read()
            item = data.get(name.strip().casefold())
            if not isinstance(item, dict) or not isinstance(item.get("paths"), list):
                return None
            paths = sorted({path for path in item["paths"]
                            if isinstance(path, str) and Path(path).is_absolute()
                            and Path(path).is_dir()})
            if paths != item["paths"]:
                item["paths"] = paths
                item["complete"] = False
                _write(data)
            if paths:
                return dict(matches=paths, complete=item.get("complete") is True)
        except (OSError, ValueError):
            pass
    return None


def remember_folders(name, paths, complete=False, replace=False):
    """Retain every match, never turn a chosen duplicate into the sole target."""
    with _lock:
        try:
            data = _read()
            key = name.strip().casefold()
            old = data.get(key, {})
            previous = old.get("paths", []) if isinstance(old, dict) else []
            if not isinstance(previous, list):
                previous = []
            candidates = list(paths) + ([] if replace else previous)
            valid = sorted({str(Path(path)) for path in candidates
                            if isinstance(path, str) and Path(path).is_absolute()
                            and Path(path).is_dir()})
            data[key] = {"paths": valid, "complete": complete}
            _write(data)
            return True
        except (OSError, ValueError):
            return False


def disk_roots():
    if os.name != "nt":
        return [Path("/")]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetLogicalDrives.restype = ctypes.c_uint32
    kernel.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
    kernel.GetDriveTypeW.restype = ctypes.c_uint
    mask = kernel.GetLogicalDrives()
    if not mask:
        raise ctypes.WinError(ctypes.get_last_error())
    return [Path(f"{chr(65 + index)}:\\") for index in range(26)
            if mask & (1 << index)
            and kernel.GetDriveTypeW(f"{chr(65 + index)}:\\") in (2, 3)]


def is_folder_name(value):
    value = value.strip().strip("\"'")
    return (bool(value) and value not in (".", "..")
            and value.casefold() not in FOLDER_ALIASES
            and not any(c in value for c in ("/", "\\", ":", "%", "$", "~")))


def search_folders(name, directory="", partial=False, max_results=100,
                   timeout_seconds=30, refresh=False):
    name = name.strip()
    if not name or name in (".", "..") or any(c in name for c in ("/", "\\", ":", "\x00")):
        raise ValueError(tr('folder_search.name_must_be_a_folder_name_not_a_path'))
    if type(max_results) is not int or not 1 <= max_results <= 1000:
        raise ValueError(tr('folder_search.max_results_must_be_between_1_and_1000'))
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 300:
        raise ValueError(tr('folder_search.timeout_seconds_must_be_between_1_and_300'))
    global_search = not directory.strip()
    if global_search and not partial and not refresh:
        cached = cached_folders(name)
        if cached:
            paths = cached["matches"]
            return dict(name=name, source="cache", matches=paths[:max_results],
                        complete=cached["complete"] and len(paths) <= max_results,
                        stop_reason="max_results" if len(paths) > max_results else None)
    roots = disk_roots() if global_search else [resolve_directory(directory)]
    if not roots:
        raise ValueError(tr('folder_search.no_local_disks_available'))
    if not global_search and not roots[0].is_dir():
        raise ValueError(tr('folder_search.search_directory_does_not_exist', value0=roots[0]))
    queues = deque(deque([root]) for root in roots)
    matches, errors = set(), []
    error_count = skipped_links = 0
    stop_reason = None
    deadline = time.monotonic() + timeout_seconds
    query = name.casefold()
    while queues and stop_reason is None:
        if time.monotonic() >= deadline:
            stop_reason = "timeout"
            break
        pending = queues.popleft()
        current = pending.popleft()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if time.monotonic() >= deadline:
                        stop_reason = "timeout"
                        break
                    try:
                        target = Path(entry.path)
                        if entry.is_symlink() or target.is_junction():
                            skipped_links += 1
                            continue
                        if not entry.is_dir(follow_symlinks=False):
                            continue
                        candidate = entry.name.casefold()
                        if (query in candidate if partial else query == candidate):
                            matches.add(str(target))
                            if len(matches) >= max_results:
                                stop_reason = "max_results"
                                break
                        pending.append(target)
                    except OSError as error:
                        error_count += 1
                        if len(errors) < 20:
                            errors.append(f"{entry.path}: {error}")
        except OSError as error:
            error_count += 1
            if len(errors) < 20:
                errors.append(f"{current}: {error}")
        if pending:
            queues.append(pending)
    complete = stop_reason is None and not error_count and not skipped_links
    saved = None
    if matches:
        if not partial:
            saved = remember_folders(name, list(matches),
                                     complete=complete and global_search,
                                     replace=complete and global_search)
        else:
            groups = {}
            for path in matches:
                groups.setdefault(Path(path).name, []).append(path)
            saved = all([remember_folders(key, paths) for key, paths in groups.items()])
    return dict(name=name, directories=[str(root) for root in roots],
                source="disks" if global_search else "directory", matches=sorted(matches),
                complete=complete, stop_reason=stop_reason, skipped_links=skipped_links,
                error_count=error_count, errors=errors, cache_saved=saved)
