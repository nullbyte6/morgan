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
#  You should have received a copy of the GNU General Public License
#  along with this program. If not, see <https://www.gnu.org/licenses/>.
"""Operating system services the core requests from the active platform package."""

from contextlib import nullcontext
from dataclasses import dataclass
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from typing import Any, Callable


class UnsupportedOperation(OSError):
    """Raised when the active platform does not provide a requested service."""

    def __init__(self, platform: str, operation: str):
        from src.init.lang import tr
        super().__init__(tr('platforms.operation_not_supported',
                            operation=operation, platform=platform))
        self.platform = platform
        self.operation = operation


class TelemetryError(OSError):
    """Raised when a system telemetry query fails, with a short code such as query_failed."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class MediaSession:
    """One media session as the system reports it, with position measured when it was read."""

    source: str
    title: str
    artist: str
    album: str
    playing: bool
    current: bool
    duration: float
    position: float
    seekable: bool
    handle: Any = None


class MediaReader:
    """Reads media sessions repeatedly; keep it on the thread that created it."""

    def sessions(self, accept: Callable[[str], bool] | None = None) -> list[MediaSession]:
        """Return sessions whose source is accepted, without cover art."""
        return []

    def cover(self, session: MediaSession) -> bytes:
        """Return the cover art of a session read by this reader."""
        return b""

    def close(self) -> None:
        pass


class PosixTerminal:
    """A shell running in a POSIX pseudo-terminal."""

    def __init__(self, argv: list[str] | None, directory: Path, environment: dict[str, str],
                 columns: int, rows: int):
        from ptyprocess import PtyProcessUnicode
        shell = os.environ.get("SHELL") or shutil.which("sh") or "/bin/sh"
        self.process = PtyProcessUnicode.spawn(
            argv or [shell, "-i"], cwd=str(directory), env=environment,
            dimensions=(rows, columns))
        self.pid = self.process.pid

    def write(self, text: str) -> None:
        self.process.write(text)

    def resize(self, columns: int, rows: int) -> None:
        self.process.setwinsize(rows, columns)

    def read(self) -> str:
        """Return pending output without waiting, raising EOFError once the terminal closed."""
        import select
        if select.select([self.process.fd], [], [], 0)[0]:
            return self.process.read(32768)
        return ""

    def isalive(self) -> bool:
        return self.process.isalive()

    def exit_status(self) -> int | None:
        return self.process.exitstatus

    def kill(self) -> None:
        """End the shell and every process it started."""
        import signal
        os.killpg(self.pid, signal.SIGKILL)

    def close(self) -> None:
        self.process.close(force=True)


class Platform:
    """Portable defaults that each platform package overrides with native services."""

    name = sys.platform
    no_window_flags = 0
    detached_flags = 0
    persistent_environment = False
    elevation_captures_output = False
    installer_name = ""
    has_drive_letters = False
    preferred_audio_host = ""
    telemetry_sources: frozenset[str] = frozenset()

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

    def media_reader(self) -> MediaReader:
        """Return a reader of the system media sessions."""
        raise self.unsupported("media_reader")

    def current_media(self) -> dict | None:
        """Describe the current system media session, or None when there is none."""
        raise self.unsupported("current_media")

    def media_sessions(self) -> list[dict]:
        """Describe every system media session."""
        raise self.unsupported("media_sessions")

    def control_media(self, action: str, source: str = "") -> str | None:
        """Send play, pause, next or previous to a media session; None when no session is active."""
        raise self.unsupported("control_media")

    def seek_media(self, seconds: float, source: str = "") -> str:
        """Move the playback position of a media session."""
        raise self.unsupported("seek_media")

    def record_output_audio(self, seconds: int, sample_rate: int):
        """Record what the default output device is playing as a float array."""
        raise self.unsupported("record_output_audio")

    def user_environment(self, name: str) -> str | None:
        """Read a per-user environment variable persisted outside this process."""
        return None

    def set_user_environment(self, name: str, value: str) -> None:
        """Persist a per-user environment variable where persistent_environment is true."""

    def lock_file(self, file, blocking: bool = True) -> None:
        """Lock the first byte of an open file, raising OSError when blocking is false and it is held."""
        import fcntl
        fcntl.flock(file, fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB)

    def unlock_file(self, file) -> None:
        import fcntl
        fcntl.flock(file, fcntl.LOCK_UN)

    def remove_link(self, path: Path) -> None:
        """Remove a link to a directory without touching its target."""
        path.unlink()

    def is_elevated(self) -> bool:
        return hasattr(os, "geteuid") and os.geteuid() == 0

    supports_shell_choice = False

    def default_shell(self) -> str:
        return "sh"

    def bash_executable(self) -> str | None:
        """Return the path of a bash that behaves like a POSIX shell, or None."""
        return shutil.which("bash")

    def elevation_prefix(self, cwd: str) -> list[str]:
        """Return the command prefix that runs a command with administrator rights in cwd."""
        from src.init.lang import tr
        sudo = shutil.which("sudo")
        if not sudo:
            raise ValueError(tr("command.sudo_missing"))
        return [sudo, "--"]

    def service_launchers(self, name: str) -> list[str]:
        """Return the file names of the script that starts Ollama and the voice service."""
        return []

    def service_command(self, script: Path, voice: bool) -> list[str]:
        """Return the command that runs a services script, optionally without the voice service."""
        raise self.unsupported("service_command")

    def unbundled_libraries(self, bundle: Path):
        """Context in which child processes do not load libraries from a frozen bundle."""
        return nullcontext()

    def installed_executable(self) -> Path | None:
        """Return the installed desktop executable."""
        return None

    def run_installer_after_exit(self, setup: Path, command: list[str], directory: Path,
                                 environment: dict[str, str]) -> None:
        """Once this process exits, run the installer, delete it and run command in directory."""
        raise self.unsupported("run_installer_after_exit")

    def raise_priority(self, process: bool) -> None:
        """Raise the priority of the current process, or of the current thread when process is false."""

    def trim_memory(self) -> None:
        """Return idle memory of the current process to the system."""

    def open_terminal(self, argv: list[str] | None, directory: Path, environment: dict[str, str],
                      columns: int, rows: int):
        """Start argv, or an interactive shell, in a pseudo-terminal of the given size."""
        return PosixTerminal(argv, directory, environment, columns, rows)

    def terminal_command_line(self, command: str) -> str:
        """Return the line that makes the interactive shell run command."""
        return "eval " + shlex.quote(command)

    def console_encoding(self) -> str:
        """Return the encoding console programs use for their output."""
        return "utf-8"

    def style_window_frame(self, handle: int, dark: bool, caption: tuple[int, int, int],
                           border: tuple[int, int, int], text: tuple[int, int, int]) -> None:
        """Color the native title bar and border of a window."""

    def window_height(self, handle: int) -> int | None:
        """Return the native frame height of a window in physical pixels, when the system reports it."""
        return None

    def set_app_id(self, app_id: str) -> None:
        """Identify this process as an independent application to the desktop shell."""

    def desktop_launcher(self, installation: Path | None, root: Path) -> Path | None:
        """Return the installed desktop executable, or the development launcher under root."""
        return None

    def launch_command(self, launcher: Path, root: Path) -> tuple[list[str], Path]:
        """Return the command and working folder that run a desktop launcher."""
        return [str(launcher)], launcher.parent

    def telemetry_query(self, source: str, full: bool = False):
        """Answer one source from telemetry_sources with JSON-like data, raising TelemetryError on failure."""
        raise self.unsupported("telemetry_query")
