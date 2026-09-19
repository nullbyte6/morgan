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
"""Resolve user-facing app names against running processes before closing."""

from src.init.lang import tr
import json
import os
from pathlib import Path
import re
import unicodedata

import psutil

from .app_cache import cached_app
from .windows import get_open_windows, request_window_close


def _normalize(name):
    name = re.sub(r"\.exe$", "", name.strip(), flags=re.I)
    return "".join(c for c in unicodedata.normalize("NFKD", name.casefold())
                   if c.isalnum())


def close_application(application: str, force: bool = False) -> str:
    """Close a running application by name, executable or PID on Windows.
    A request such as 'close Spotify' authorizes normal closure. Resolve against
    running processes; return candidates if ambiguous. force=True is only for
    explicitly requested forced termination. Normal window closure can leave
    save dialogs or a tray process running; report requested, not terminated.
    """
    def result(status, **values):
        return json.dumps(dict(status=status, **values), ensure_ascii=False)

    if os.name != "nt":
        return result("error", error=tr('app_close.closing_applications_is_supported_on_windows_only'))
    query = _normalize(application)
    if not query:
        return result("error", error=tr('app_close.an_application_name_is_required'))
    try:
        from .brain import kill_process, normalize_application_name
        app = cached_app(normalize_application_name(application))
        cached_name = _normalize(Path(app["Path"]).name) if app and app.get("Path") else None
        if query in {"explorador de archivos", "explorador", "fileexplorer",
                     "windowsexplorer"}:
            query = "explorer"
        processes = []
        for process in psutil.process_iter(["pid", "name", "create_time"]):
            try:
                info = process.info
                if info.get("name"):
                    processes.append(dict(pid=info["pid"], executable=info["name"],
                                          created=info["create_time"]))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        exact = [p for p in processes if (
            str(p["pid"]) == application.strip() or
            _normalize(p["executable"]) in {query, cached_name})]
        matches = exact or [p for p in processes if query in _normalize(p["executable"])]
        if not matches:
            return result("not_found", application=application)
        groups = sorted({p["executable"] for p in matches})
        if len(groups) > 1:
            return result("needs_input", candidates=matches,
                          question=tr('app_close.which_app_do_you_want_to_close_tell_me_the_pid_or_the_executable'))
        windows = get_open_windows()
        outcomes = []
        for match in matches:
            pid = match["pid"]
            try:
                current = psutil.Process(pid)
                if current.create_time() != match["created"]:
                    outcomes.append(dict(pid=pid, status="changed"))
                    continue
                if pid <= 4 or pid == os.getpid() or _normalize(match["executable"]) in {
                    "system", "registry", "csrss", "lsass", "services", "smss", "wininit", "winlogon"}:
                    outcomes.append(dict(pid=pid, status="refused"))
                    continue
                targets = [w for w in windows if w["pid"] == pid]
                explorer = _normalize(match["executable"]) == "explorer"
                if targets and (not force or explorer):
                    for window in targets:
                        request_window_close(window["hwnd"], pid)
                    outcomes.append(dict(pid=pid, status="close_requested", windows=len(targets)))
                elif explorer:
                    outcomes.append(dict(pid=pid, status="no_open_windows"))
                else:
                    message = kill_process(str(pid), force=force)
                    outcomes.append(dict(pid=pid, status="terminated" if message.startswith(
                        tr('app_close.process_terminated')) else "failed", detail=message))
            except psutil.NoSuchProcess:
                outcomes.append(dict(pid=pid, status="already_closed"))
            except (OSError, psutil.AccessDenied) as error:
                outcomes.append(dict(pid=pid, status="failed", error=str(error)))
        return result("results", application=application, outcomes=outcomes,
                      note=tr('app_close.close_requested_means_a_normal_close_request_not_confirmed_termi'))
    except (OSError, psutil.Error) as error:
        return result("error", error=str(error))
