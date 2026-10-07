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
"""Linux services for Morgan, backed by X11 window tools, MPRIS, freedesktop notifications and systemd."""

from pathlib import Path
import subprocess

from ..base import Platform
from . import apps, desktop, folders, media, notifications, services, system, telemetry, windows


class LinuxX64Platform(Platform):
    name = "linuxx64"
    telemetry_sources = frozenset(telemetry.SOURCES)
    telemetry_query = staticmethod(telemetry.telemetry_query)
    preferred_audio_host = ""
    output_latency = "high"

    list_windows = staticmethod(windows.get_open_windows)
    launch_application = staticmethod(windows.launch_application)
    request_window_close = staticmethod(windows.request_window_close)
    minimize_window = staticmethod(windows.minimize_window)
    known_folder = staticmethod(folders.known_folder)
    local_drives = staticmethod(folders.local_drives)
    terminate_process = staticmethod(system.terminate_process)
    schedule_shutdown = staticmethod(system.schedule_shutdown)
    cancel_shutdown = staticmethod(system.cancel_shutdown)
    installed_applications = staticmethod(system.installed_applications)
    empty_recycle_bin = staticmethod(system.empty_recycle_bin)
    package_command = staticmethod(apps.package_command)
    app_data_roots = staticmethod(apps.app_data_roots)
    steam_path = staticmethod(apps.steam_path)
    notify = staticmethod(notifications.notify)
    ask_notification = staticmethod(notifications.ask_notification)
    media_reader = staticmethod(media.LinuxMediaReader)
    current_media = staticmethod(media.current_media)
    media_sessions = staticmethod(media.media_sessions)
    control_media = staticmethod(media.control_media)
    seek_media = staticmethod(media.seek_media)
    record_output_audio = staticmethod(media.record_output_audio)
    set_app_id = staticmethod(desktop.set_app_id)
    desktop_launcher = staticmethod(desktop.desktop_launcher)
    launch_command = staticmethod(desktop.launch_command)
    installed_executable = staticmethod(services.installed_executable)
    service_launchers = staticmethod(services.service_launchers)
    service_command = staticmethod(services.service_command)
    unbundled_libraries = staticmethod(services.unbundled_libraries)

    def open_path(self, path: Path | str) -> None:
        subprocess.Popen(["xdg-open", str(path)], env=services.system_environment(),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
