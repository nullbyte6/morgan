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
"""General shell execution with consent collected directly from the user."""

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess

from .identity import get_assistant

import ctypes
from collections.abc import Callable
from contextvars import ContextVar
from .lang import tr

from .brain import get_working_directory
from src.platforms import current_platform


_confirmation = ContextVar("command_confirmation", default=None)
_terminal_executor = None


def set_terminal_executor(executor) -> None:
    """Attach the desktop's GUI-thread terminal dispatcher."""
    global _terminal_executor
    _terminal_executor = executor


def set_confirmation_handler(handler: Callable[[str], bool] | None) -> None:
    _confirmation.set(handler)


def is_elevated() -> bool:
    if os.name != "nt":
        return hasattr(os, "geteuid") and os.geteuid() == 0

    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False



def _confirm(message: str) -> bool:
    handler = _confirmation.get()
    if handler is not None:
        try:
            return bool(handler(message))
        except Exception:
            return False

    try:
        answer = get_assistant().read_user_input(message + tr("command.answer"))
        return answer.strip().casefold() in {"sí", "si", "yes", "y"}
    except (EOFError, KeyboardInterrupt, RuntimeError):
        return False



def _encoded(script: str) -> str:
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def _shell_command(command: str, shell: str) -> list[str]:
    executable = shutil.which(shell)
    if executable is None:
        raise ValueError(tr("command.shell_unavailable", shell=shell))
    if shell in {"powershell", "pwsh"}:
        script = ("$ErrorActionPreference = 'Stop'; $global:LASTEXITCODE = 0; "
                  "try { & {\n" + command + "\n}; "
                  "if (-not $?) { exit 1 }; exit $LASTEXITCODE "
                  "} catch { [Console]::Error.WriteLine($_); exit 1 }")
        return [executable, "-NoProfile", "-EncodedCommand", _encoded(script)]
    if shell == "cmd":
        return [executable, "/d", "/s", "/c", command]
    return [executable, "-c", command]


def _windows_elevated(argv: list[str], cwd: str) -> subprocess.CompletedProcess:
    """Use Windows sudo in the user's configured mode, without a fallback."""
    sudo = shutil.which("sudo.exe")
    if not sudo:
        raise ValueError(tr("command.sudo_unavailable"))
    return subprocess.run(
        [sudo, "--chdir", cwd, "--", *argv], cwd=cwd,
        stdin=subprocess.DEVNULL, capture_output=True, text=True,
        errors="replace",
    )


def execute_command(command: str, working_directory: str = ".",
                    shell: str = "auto", elevated: bool = False,
                    timeout_seconds: int = 120) -> str:
    """Open a built-in terminal workspace and execute a command after consent.
    In desktop mode the command runs in the visible terminal, with live output.
    Without the desktop, capture output directly in the current CLI session.
    Supports pipelines, scripts, shell builtins and installed executables.
    shell: auto, powershell, pwsh, cmd, sh or bash (case-insensitive). On Windows auto is
    PowerShell. elevated asks separately for sudo (Windows and POSIX).
    Never retry failed commands automatically: they may have partially run.
    Windows sudo must be enabled and uses the user's configured mode.
    Desktop commands accept input in their terminal panel. CLI commands have
    closed stdin except POSIX sudo and Windows new-window mode.
    Windows elevated output may appear in a separate window;
    elevated commands wait until completion without a timeout.
    """
    context = {"command": command, "elevated": elevated}

    def result(status, **values):
        return json.dumps(dict(context, status=status, **values), ensure_ascii=False)

    try:
        if not command.strip() or "\x00" in command:
            raise ValueError(tr("command.empty"))
        if not 1 <= timeout_seconds <= 86400:
            raise ValueError(tr("command.timeout_range"))

        shell = shell.strip().casefold().removesuffix(".exe")
        if shell == "auto":
            if os.name == "nt":
                shell = "pwsh" if shutil.which("pwsh") else "powershell"
            else:
                shell = "sh"

        if shell not in {"powershell", "pwsh", "cmd", "sh", "bash"}:
            raise ValueError(tr("command.unsupported_shell"))

        if working_directory == ".":
            working_directory = get_working_directory()

        cwd = str(Path(working_directory).expanduser().resolve(strict=True))
        if not Path(cwd).is_dir():
            raise ValueError(tr("command.not_directory"))
        argv = _shell_command(command, shell)
        context.update(working_directory=cwd, shell=shell)
        preview = json.dumps(command, ensure_ascii=False)
        if not _confirm(tr("command.confirm", cwd=json.dumps(cwd), shell=shell, preview=preview)):
            return result("denied")
        if elevated and not is_elevated():
            if not _confirm(tr("command.elevated")):
                return result("denied")
            if _terminal_executor is not None:
                sudo = shutil.which("sudo.exe" if os.name == "nt" else "sudo")
                if not sudo:
                    raise ValueError(tr("command.sudo_unavailable" if os.name == "nt"
                                        else "command.sudo_missing"))
                prefix = [sudo, "--chdir", cwd, "--"] if os.name == "nt" else [sudo, "--"]
                return result(**_terminal_executor(prefix + argv, cwd, command, None))
            if os.name == "nt":
                completed = _windows_elevated(argv, cwd)
                return result("completed" if completed.returncode == 0 else "failed",
                              exit_code=completed.returncode,
                              stdout=completed.stdout[-32000:], stderr=completed.stderr[-32000:],
                              output_truncated=max(len(completed.stdout), len(completed.stderr)) > 32000,
                              output_may_be_in_separate_window=True,
                              note=tr("command.sudo_note"))
            sudo = shutil.which("sudo")
            if not sudo:
                raise ValueError(tr("command.sudo_missing"))
            completed = subprocess.run([sudo, "--", *argv], cwd=cwd)
            return result("completed" if completed.returncode == 0 else "failed",
                          exit_code=completed.returncode, output_captured=False)
        if _terminal_executor is not None:
            return result(**_terminal_executor(argv, cwd, command, timeout_seconds))
        completed = subprocess.run(
            argv, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True,
            text=True, errors="replace", timeout=timeout_seconds,
            creationflags=current_platform().no_window_flags)
        return result("completed" if completed.returncode == 0 else "failed",
                      exit_code=completed.returncode,
                      stdout=completed.stdout[-32000:], stderr=completed.stderr[-32000:],
                      output_truncated=max(len(completed.stdout), len(completed.stderr)) > 32000)
    except subprocess.TimeoutExpired:
        return result("timeout", note=tr("command.timeout_note"))
    except (OSError, ValueError, RuntimeError) as error:
        return result("error", error=str(error))
