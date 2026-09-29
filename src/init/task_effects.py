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
"""Explicit tool effects and content revisions, independent of the model runtime."""

import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .paths import PROJECT_ROOT
from .task_outcomes import ActionResult, Outcome, normalize_result


@dataclass(frozen=True)
class ToolSpec:
    effectful: bool
    domain: str = ""
    path_argument: str = ""
    source: bool = False
    text_observation: bool = False
    ancillary: bool = False
    verification_capable: bool = False
    requires_followup: bool = False
    followup_policy: Callable[[ActionResult], bool] | None = None
    actions_policy: Callable[[dict], list[dict]] | None = None

    def needs_followup(self, result: ActionResult) -> bool:
        if self.followup_policy is not None:
            return self.followup_policy(result)
        return self.requires_followup and result.successful

    def actions_for(self, arguments: dict) -> list[dict] | None:
        if self.actions_policy is not None:
            return self.actions_policy(arguments)
        return None


TOOL_SPECS = {}


def register(names, spec):
    for name in names.split():
        if name in TOOL_SPECS:
            raise ValueError(f"Duplicate tool effect declaration: {name}")
        TOOL_SPECS[name] = spec


def app_operation_followup(result: ActionResult) -> bool:
    data = result.data
    return (result.outcome in {Outcome.SUCCESS, Outcome.UNCERTAIN}
            and isinstance(data, dict) and data.get("status") == "running"
            and isinstance(data.get("job_id"), str) and bool(data["job_id"].strip()))


def quick_command_actions(arguments: dict) -> list[dict]:
    from .quick_commands import _prepare_actions, load_quick_commands
    from .tools import TOOLS

    commands = load_quick_commands()
    matches = [definition for name, definition in commands.items()
               if name.casefold() == arguments.get("name", "").strip().casefold()]
    if len(matches) != 1:
        raise ValueError("Choose one existing quick-command group.")
    prepared = _prepare_actions(matches[0]["actions"], {tool.__name__: tool for tool in TOOLS})
    return [{"tool": name, "arguments": dict(bound.arguments)}
            for _, _, name, _, bound in prepared]


def quick_command_followup(result: ActionResult) -> bool:
    data = result.data
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        return False
    for item in data["results"]:
        if not isinstance(item, dict) or "output" not in item:
            continue
        spec = TOOL_SPECS.get(item.get("tool"))
        if spec is not None and spec.needs_followup(normalize_result(
                item["output"], text_observation=spec.text_observation)):
            return True
    return False


register("get_version get_current_time calculate get_city_distance get_weather "
         "search_youtube_songs search_spotify_songs search_spotify_playlists search_spotify_albums "
         "list_spotify_playlists get_spotify_playlist_tracks read_clipboard analyze_image analyze_screen "
         "find_directories list_quick_commands read_attachment", ToolSpec(False))
register("search_web read_web_page", ToolSpec(True, "web", ancillary=True, verification_capable=True))
register("recall list_memories search_words word_instances read_conversation read_memory_message",
         ToolSpec(False, "memory"))
register("remember forget", ToolSpec(True, "memory"))
register("list_media_sessions identify_playing_song get_current_media", ToolSpec(False, "media"))
register("control_media play_youtube_song play_spotify_song play_spotify_album play_spotify_playlist",
         ToolSpec(True, "media"))
register("list_steam_games find_steam_game list_applications list_open_applications",
         ToolSpec(False, "applications"))
register("search_apps get_app_operation", ToolSpec(False, "applications", followup_policy=app_operation_followup))
register("scan_app_residues", ToolSpec(False, "applications"))
register("open_application launch_steam_game close_application",
         ToolSpec(True, "applications"))
register("install_app uninstall_app", ToolSpec(True, "applications", followup_policy=app_operation_followup))
register("clean_app_residue", ToolSpec(True, "applications"))
register("check_system_health check_disk_health check_security_health", ToolSpec(False, "system"))
register("kill_self refresh empty_recycle_bin kill_process shutdown_computer cancel_shutdown", ToolSpec(True, "system"))
register("run_quick_command", ToolSpec(True, "system", followup_policy=quick_command_followup,
                                      actions_policy=quick_command_actions))
register("execute_command", ToolSpec(True, "system", verification_capable=True))
register("get_email_draft read_emails", ToolSpec(False, "email"))
register("draft_email edit_email_draft send_email_draft send_email delete_email", ToolSpec(True, "email"))
register("send_message", ToolSpec(True, "messages"))
register("list_timers", ToolSpec(False, "notifications"))
register("send_notification schedule_notification start_timer cancel_timer", ToolSpec(True, "notifications"))
register("load_config", ToolSpec(False, "config"))
register("update_config set_weather_location learn_pronunciation", ToolSpec(True, "config"))
register("read_notes", ToolSpec(False, "notes"))
register("save_note", ToolSpec(True, "notes"))
register("get_working_directory", ToolSpec(False, "working_directory", text_observation=True))
register("change_directory", ToolSpec(True, "working_directory"))
register("get_repo", ToolSpec(False, "git", path_argument="repository", source=True))
register("list_code search_code", ToolSpec(False, path_argument="directory", source=True))
register("read_code verify_code", ToolSpec(False, path_argument="path", source=True))
register("edit_code create_code", ToolSpec(True, path_argument="path", source=True))
register("update_repo", ToolSpec(True, "git", path_argument="repository", source=True))
register("list_files", ToolSpec(False, path_argument="path"))
register("read_file read_binary_file", ToolSpec(False, path_argument="path"))
register("create_file edit_file append_file replace_in_file write_binary_file delete_file "
         "create_directory rename_directory delete_directory", ToolSpec(True, path_argument="path"))
register("git_status git_diff git_log git_list_branches", ToolSpec(False, "git", path_argument="repository"))
register("git_add git_commit git_fetch git_pull git_push git_switch", ToolSpec(True, "git", path_argument="repository"))
register("open_file open_directory open_browser get_repo_lnk open_current_session_log open_in_editor "
         "minimize_all_windows take_screenshot", ToolSpec(True, "presentation"))
register("render_flowchart", ToolSpec(True, "presentation", ancillary=True, verification_capable=True))


def file_resource(path):
    from .brain import resolve_safe_path
    return "file:" + str(resolve_safe_path(path))


def entry_resource(path):
    from .brain import resolve_entry_path
    path = resolve_entry_path(path)
    return "entry:" + str(path.parent.resolve() / path.name)


def contains(scope, resource):
    if scope == resource:
        return True
    if scope.startswith(("file:", "entry:")) and resource.startswith(("file:", "entry:")):
        return Path(resource.split(":", 1)[1]).is_relative_to(Path(scope.split(":", 1)[1]))
    return False


def content_revision(resource):
    if resource.startswith("domain:git:"):
        path = resource[len("domain:git:"):]
        digest = hashlib.sha256()
        try:
            for arguments in (("show-ref", "--head"), ("symbolic-ref", "--quiet", "HEAD"),
                              ("diff", "--cached", "--binary", "--no-ext-diff")):
                result = subprocess.run(["git", "-C", path, *arguments], capture_output=True, timeout=15,
                                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                if result.returncode not in (0, 1) or (result.returncode and result.stderr):
                    return None
                digest.update(result.stdout)
            return digest.hexdigest()
        except (OSError, subprocess.TimeoutExpired):
            return None
    if not resource.startswith(("file:", "entry:")):
        return None
    path = Path(resource.split(":", 1)[1])
    digest = hashlib.sha256()
    try:
        if not path.exists() and not path.is_symlink():
            return "missing"
        if path.is_symlink() or path.is_junction():
            return "link:" + os.readlink(path)
        if path.is_file():
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest()
        tracked = None
        if shutil.which("git"):
            tracked = subprocess.run(["git", "-C", str(path), "ls-files", "--cached", "--others",
                                      "--exclude-standard", "-z", "--", "."], capture_output=True,
                                     timeout=15, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if tracked is not None and tracked.returncode == 0:
            for name in sorted(set(tracked.stdout.decode("utf-8", errors="surrogateescape").split("\0")) - {""}):
                child = path / name
                digest.update(name.encode("utf-8", errors="surrogateescape"))
                revision = content_revision(entry_resource(child))
                if revision is None:
                    return None
                digest.update(revision.encode())
            return digest.hexdigest()
        for root, directories, files in os.walk(path, followlinks=False):
            directories[:] = sorted(name for name in directories
                                    if name not in {".git", ".venv", "__pycache__"}
                                    and not Path(root, name).is_symlink()
                                    and not Path(root, name).is_junction())
            digest.update(str(Path(root).relative_to(path)).encode())
            for name in sorted(files):
                child = Path(root, name)
                digest.update(name.encode())
                revision = content_revision(entry_resource(child))
                if revision is None:
                    return None
                digest.update(revision.encode())
        return digest.hexdigest()
    except (OSError, subprocess.TimeoutExpired):
        return None


def resources_for(name, arguments):
    spec = TOOL_SPECS.get(name)
    if spec is None:
        raise ValueError(f"Tool has no effect declaration: {name}")
    resources = []
    if spec.domain:
        from .brain import get_working_directory
        resources.append("domain:" + spec.domain + (":" + str((PROJECT_ROOT if spec.source else Path(get_working_directory())).joinpath(arguments.get("repository", ".")).resolve())
                                                        if spec.domain == "git" else ""))
    if spec.path_argument:
        from .brain import get_working_directory
        base = PROJECT_ROOT if spec.source else Path(get_working_directory())
        path = arguments.get(spec.path_argument, ".")
        if name == "read_code" and arguments.get("cursor"):
            from .self_code import code_cursor
            path = code_cursor(arguments["cursor"])["path"]
        make_resource = entry_resource if name in {"delete_file", "delete_directory", "rename_directory"} else file_resource
        resources.append(make_resource(base / path))
        if name == "rename_directory" and arguments.get("new_name"):
            resources.append(entry_resource((base / path).with_name(arguments["new_name"])))
    if name in {"execute_command", "run_quick_command"}:
        resources.append(file_resource(arguments.get("working_directory", ".")))
    if name == "search_web" or name == "read_web_page" and arguments.get("show_in_browser", False):
        resources.append("domain:presentation")
    if name == "run_quick_command":
        from .quick_commands import TOOL_ALIASES, load_quick_commands
        commands = load_quick_commands()
        matches = [definition for key, definition in commands.items()
                   if key.casefold() == arguments.get("name", "").strip().casefold()]
        if len(matches) != 1:
            raise ValueError("Choose one existing quick-command group.")
        for action in matches[0]["actions"]:
            child = TOOL_ALIASES.get(action["tool"], action["tool"])
            if child == "run_quick_command":
                raise ValueError("Quick commands cannot recursively run quick commands.")
            values = action.get("arguments", {})
            if "value" in action:
                from .tools import TOOLS
                import inspect
                function = next(tool for tool in TOOLS if tool.__name__ == child)
                values = dict(inspect.signature(function).bind(action["value"]).arguments)
            _, child_resources = resources_for(child, values)
            resources.extend(child_resources)
    return spec, list(dict.fromkeys(resources))
