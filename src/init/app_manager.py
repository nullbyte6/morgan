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
"""Windows package management and scoped, recoverable application cleanup."""
from src.init.lang import tr
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import uuid

_jobs = {}
_candidates = {}
_lock = threading.RLock()
from .config import DEFAULTS, HOME_PATH
from .identity import get_assistant_identifier

_SHARED = {"microsoft", "windows", "packages", "programs", "temp", "cache",
           "google", "mozilla", "adobe", "common files", DEFAULTS["assistant"]["name"].casefold(), "." + DEFAULTS["assistant"]["name"].casefold(), HOME_PATH.name, get_assistant_identifier()}


def _result(status, **values):
    return json.dumps({"status": status, **values}, ensure_ascii=False)


def _argument(value):
    value = value.strip()
    if not value.strip() or value.startswith("-") or any(
            ord(c) < 32 for c in value):
        raise ValueError(
            tr('app_manager.specify_a_non_empty_name_or_exact_package_id_not_command_options'))
    return value.strip()


def _winget():
    executable = shutil.which("winget")
    if not executable and os.environ.get("LOCALAPPDATA"):
        alias = Path(
            os.environ["LOCALAPPDATA"]) / "Microsoft/WindowsApps/winget.exe"
        if alias.is_file():
            executable = str(alias)
    if not executable:
        raise ValueError(
            tr('app_manager.winget_is_unavailable_install_update_microsoft_app_installer_and'))
    return executable


def _start(arguments, mutation=False):
    if os.name != "nt":
        return _result("error", error=tr('app_manager.application_management_requires_windows'))
    with _lock:
        try:
            if mutation and any(
                    j["mutation"] and j["process"].poll() is None for j in
                    _jobs.values()):
                return _result("error",
                               error=tr('app_manager.an_app_operation_is_still_running_check_its_job_id_first'))
            command = [_winget(), *arguments, "--accept-source-agreements",
                       "--disable-interactivity"]
            log = tempfile.TemporaryFile()
            try:
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                           stdout=log,
                                           stderr=subprocess.STDOUT,
                                           shell=False,
                                           creationflags=subprocess.CREATE_NO_WINDOW)
            except OSError:
                log.close()
                raise
            job_id = uuid.uuid4().hex
            _jobs[job_id] = {"process": process, "log": log,
                             "mutation": mutation}
            return _result("running", job_id=job_id, command=command,
                           instruction=tr('app_manager.use_get_app_operation_until_finished_do_not_repeat_the_operation'))
        except (OSError, ValueError) as error:
            return _result("error", error=str(error))


def get_app_operation(job_id: str) -> str:
    """Check a winget operation in this Arlo session. Only completed means exit code zero."""
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return _result("unknown", error=tr('app_manager.unknown_job_or_assistant_restarted_inspect_installed_apps_before_retr'))
        if "result" in job:
            return job["result"]
        code = job["process"].poll()
        if code is None:
            return _result("running", job_id=job_id)
        log = job["log"]
        length = log.seek(0, os.SEEK_END)
        log.seek(max(0, length - 24000))
        output = log.read().decode("utf-8", errors="replace")
        log.close()
        job["result"] = _result("completed" if code == 0 else "error",
                                job_id=job_id,
                                exit_code=code, output=output,
                                truncated=length > 24000,
                                instruction=tr('app_manager.report_winget_output_errors_or_elevation_requests_require_attent'))
        return job["result"]


def search_apps(query: str, installed_only: bool = False) -> str:
    """Find winget package IDs. installed_only lists matching installed applications."""
    try:
        return _start(["list" if installed_only else "search", "--query",
                       _argument(query)])
    except ValueError as error:
        return _result("error", error=str(error))


def install_app(package_id: str, download_only: bool = False) -> str:
    """Download and install an exact winget package ID from search_apps; download_only saves to Downloads."""
    try:
        args = ["download" if download_only else "install", "--id",
                _argument(package_id),
                "--exact", "--source", "winget", "--accept-package-agreements"]
        if not download_only:
            args.append("--silent")
        return _start(args, mutation=True)
    except ValueError as error:
        return _result("error", error=str(error))


def uninstall_app(package_id: str, purge_portable: bool = False) -> str:
    """Uninstall an exact installed ID. purge_portable deletes portable package files only when requested."""
    try:
        args = ["uninstall", "--id", _argument(package_id), "--exact",
                "--silent"]
        if purge_portable:
            args.append("--purge")
        return _start(args, mutation=True)
    except ValueError as error:
        return _result("error", error=str(error))


def _roots():
    return [Path(os.environ[key]).absolute() for key in
            ("LOCALAPPDATA", "APPDATA", "PROGRAMDATA")
            if os.environ.get(key)]


def _linked(path):
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & 0x400)


def _safe(path, root):
    if path.parent != root or path.name.casefold() in _SHARED or path.name.startswith(
            "."):
        raise ValueError(
            tr('app_manager.only_individual_app_data_folders_are_eligible_never_shared_paren'))
    for ancestor in (path, *path.parents):
        if _linked(ancestor):
            raise ValueError(tr('app_manager.links_and_windows_junctions_are_excluded'))
    if path.resolve().parent != root.resolve() or not path.is_dir():
        raise ValueError(tr('app_manager.app_folder_is_outside_its_expected_data_root'))


def scan_app_residues(app_name: str) -> str:
    """Find possible app data folders (not proof of orphan status). Return candidates for explicit selection."""
    term = app_name.strip().casefold()
    if len(term) < 3 or term in _SHARED or not re.fullmatch(r"[\w .+()-]+",
                                                            term):
        return _result("error",
                       error=tr('app_manager.specify_a_distinctive_app_name_of_at_least_three_characters'))
    results, errors = [], []
    for root in _roots():
        try:
            for path in root.iterdir():
                if term not in path.name.casefold():
                    continue
                try:
                    _safe(path, root)
                    info = path.stat()
                    token = uuid.uuid4().hex
                    with _lock:
                        _candidates[token] = (path, root, info.st_dev,
                                              info.st_ino)
                    results.append({"candidate_id": token, "path": str(path)})
                except (OSError, ValueError):
                    continue
        except OSError as error:
            errors.append(str(error))
    return _result("ok", candidates=results, errors=errors,
                   instruction=tr('app_manager.name_matches_may_contain_settings_or_user_data_of_installed_apps'),
                   scope=tr('app_manager.top_level_localappdata_roaming_appdata_and_programdata_folders_o'))


def clean_app_residue(candidate_id: str) -> str:
    """Move one explicitly selected scan candidate to the Recycle Bin; never pass invented paths or IDs."""
    with _lock:
        if any(j["mutation"] and j["process"].poll() is None for j in
               _jobs.values()):
            return _result("error",
                           error=tr('app_manager.wait_for_the_running_app_operation_to_finish_before_cleanup'))
        candidate = _candidates.get(candidate_id)
        if not candidate:
            return _result("error",
                           error=tr('app_manager.unknown_candidate_scan_again_and_select_a_folder'))
        path, root, device, inode = candidate
        try:
            _safe(path, root)
            info = path.stat()
            if (info.st_dev, info.st_ino) != (device, inode):
                raise ValueError(tr('app_manager.folder_changed_since_scan_scan_again'))

            def fail(error):
                raise error

            for current, directories, files in os.walk(path, followlinks=False,
                                                       onerror=fail):
                for name in directories + files:
                    if _linked(Path(current) / name):
                        raise ValueError(
                            tr('app_manager.folder_contains_links_or_junctions_cleanup_skipped'))
            from send2trash import send2trash
            send2trash(str(path))
            del _candidates[candidate_id]
            return _result("recycled", path=str(path),
                           recovery=tr('app_manager.windows_recycle_bin'),
                           disk_space_reclaimed=False)
        except ImportError:
            return _result("error",
                           error=tr('app_manager.install_assistant_requirements_send2trash_to_enable_recoverable_clean'))
        except (OSError, ValueError) as error:
            return _result("error", error=str(error))
