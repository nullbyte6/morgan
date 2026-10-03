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
"""Operating system services the core requests from the active platform package."""

from pathlib import Path
import shutil
import subprocess
import sys


class UnsupportedOperation(OSError):
    """Raised when the active platform does not provide a requested service."""

    def __init__(self, platform: str, operation: str):
        from src.init.lang import tr
        super().__init__(tr('platforms.operation_not_supported',
                            operation=operation, platform=platform))
        self.platform = platform
        self.operation = operation


class Platform:
    """Portable defaults that each platform package overrides with native services."""

    name = sys.platform
    no_window_flags = 0

    def unsupported(self, operation: str) -> UnsupportedOperation:
        return UnsupportedOperation(self.name, operation)

    def list_windows(self) -> list[dict]:
        """Return taskbar-style application windows with handle, title, executable and pid."""
        raise self.unsupported("list_windows")

    def launch_application(self, target: str, timeout: float = 8.0) -> dict:
        """Launch a target and report whether a matching window was confirmed."""
        raise self.unsupported("launch_application")

    def request_window_close(self, handle: int, expected_pid: int) -> None:
        """Ask a window to close normally, verifying it still belongs to expected_pid."""
        raise self.unsupported("request_window_close")

    def minimize_window(self, handle: int) -> bool:
        """Minimize one window and return whether the request was accepted."""
        raise self.unsupported("minimize_window")

    def known_folder(self, name: str) -> Path:
        """Resolve documents, desktop or downloads for the current user."""
        return Path.home() / name.capitalize()

    def local_drives(self, removable: bool = True) -> list[Path]:
        """Return the roots of local disks, optionally including removable ones."""
        return [Path("/")]

    def notify(self, title: str, message: str, app_name: str) -> None:
        """Show a system notification."""
        raise self.unsupported("notify")

    def ask_notification(self, title: str, message: str, actions: list[tuple[str, str]],
                         wait_seconds: int, app_name: str) -> str:
        """Show a notification with buttons and return the chosen action ID or an empty string."""
        raise self.unsupported("ask_notification")

    def open_path(self, path: Path | str) -> None:
        """Open a file, folder or URI with its default application."""
        opener = "open" if shutil.which("open") else "xdg-open"
        subprocess.Popen([opener, str(path)])

    def terminate_process(self, process: str, force: bool = False,
                          include_children: bool = False) -> str:
        """End a process by PID or executable name and return a user-facing result."""
        raise self.unsupported("terminate_process")

    def schedule_shutdown(self, delay_seconds: int, reason: str) -> tuple[bool, str]:
        """Schedule a system shutdown and return success with the system's output."""
        raise self.unsupported("schedule_shutdown")

    def cancel_shutdown(self) -> tuple[bool, str]:
        """Cancel a pending shutdown and return success with the system's output."""
        raise self.unsupported("cancel_shutdown")

    def installed_applications(self) -> list[dict[str, str]]:
        """Return launchable applications registered with the system."""
        return []

    def empty_recycle_bin(self) -> None:
        """Permanently empty the system trash."""
        raise self.unsupported("empty_recycle_bin")

    def package_command(self, operation: str, package: str, option: bool = False) -> list[str]:
        """Build the package manager command for search, list, install, download or uninstall.
        option means silent install for install and purge for uninstall."""
        raise self.unsupported("package_command")

    def app_data_roots(self) -> list[Path]:
        """Return the folders where applications keep per-app data."""
        return []

    def steam_path(self) -> Path | None:
        """Return the local Steam installation folder."""
        return None
