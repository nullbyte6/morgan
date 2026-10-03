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
"""Windows x64 services for Arlo, backed by Win32, the Shell and PowerShell."""

import subprocess

from ..base import Platform
from . import apps, desktop, environment, folders, media, notifications, services, system, terminal, windows


class WinX64Platform(Platform):
    name = "winx64"
    no_window_flags = subprocess.CREATE_NO_WINDOW
    detached_flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    persistent_environment = True
    elevation_captures_output = True
    installer_name = "ArloSetup.exe"
    has_drive_letters = True
    preferred_audio_host = "Windows WASAPI"

    list_windows = staticmethod(windows.get_open_windows)
    launch_application = staticmethod(windows.launch_application)
    request_window_close = staticmethod(windows.request_window_close)
    minimize_window = staticmethod(windows.minimize_window)
    known_folder = staticmethod(folders.known_folder)
    local_drives = staticmethod(folders.local_drives)
    notify = staticmethod(notifications.notify)
    ask_notification = staticmethod(notifications.ask_notification)
    open_path = staticmethod(system.open_path)
    terminate_process = staticmethod(system.terminate_process)
    schedule_shutdown = staticmethod(system.schedule_shutdown)
    cancel_shutdown = staticmethod(system.cancel_shutdown)
    installed_applications = staticmethod(system.installed_applications)
    empty_recycle_bin = staticmethod(system.empty_recycle_bin)
    package_command = staticmethod(apps.package_command)
    app_data_roots = staticmethod(apps.app_data_roots)
    steam_path = staticmethod(apps.steam_path)
    media_reader = staticmethod(media.WinMediaReader)
    current_media = staticmethod(media.current_media)
    media_sessions = staticmethod(media.media_sessions)
    control_media = staticmethod(media.control_media)
    seek_media = staticmethod(media.seek_media)
    record_output_audio = staticmethod(media.record_output_audio)
    user_environment = staticmethod(environment.user_environment)
    set_user_environment = staticmethod(environment.set_user_environment)
    lock_file = staticmethod(environment.lock_file)
    unlock_file = staticmethod(environment.unlock_file)
    remove_link = staticmethod(environment.remove_link)
    is_elevated = staticmethod(environment.is_elevated)
    default_shell = staticmethod(environment.default_shell)
    elevation_prefix = staticmethod(environment.elevation_prefix)
    service_launchers = staticmethod(services.service_launchers)
    service_command = staticmethod(services.service_command)
    unbundled_libraries = staticmethod(services.unbundled_libraries)
    installed_executable = staticmethod(services.installed_executable)
    run_installer_after_exit = staticmethod(services.run_installer_after_exit)
    raise_priority = staticmethod(services.raise_priority)
    trim_memory = staticmethod(services.trim_memory)
    open_terminal = staticmethod(terminal.WinTerminal)
    terminal_command_line = staticmethod(terminal.terminal_command_line)
    console_encoding = staticmethod(terminal.console_encoding)
    style_window_frame = staticmethod(desktop.style_window_frame)
    window_height = staticmethod(desktop.window_height)
    set_app_id = staticmethod(desktop.set_app_id)
    desktop_launcher = staticmethod(desktop.desktop_launcher)
    launch_command = staticmethod(desktop.launch_command)
