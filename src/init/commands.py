"""General shell execution with consent collected directly from the user."""

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess

from .identity import get_assistant


def _confirm(message: str) -> bool:
    try:
        answer = get_assistant().read_user_input(message + " [yes/no]: ")
        return answer.strip().casefold() in {"sí", "si", "yes", "y"}
    except (EOFError, KeyboardInterrupt, RuntimeError):
        return False


def _encoded(script: str) -> str:
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def _shell_command(command: str, shell: str) -> list[str]:
    executable = shutil.which(shell)
    if executable is None:
        raise ValueError(f"Shell unavailable: {shell}")
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
        raise ValueError("Windows sudo is unavailable. Enable sudo in Windows Settings.")
    return subprocess.run(
        [sudo, "--chdir", cwd, "--", *argv], cwd=cwd,
        stdin=subprocess.DEVNULL, capture_output=True, text=True,
        errors="replace",
    )


def execute_command(command: str, working_directory: str = ".",
                    shell: str = "auto", elevated: bool = False,
                    timeout_seconds: int = 120) -> str:
    """Run any local shell command after direct terminal consent.

    Supports pipelines, scripts, shell builtins and installed executables.
    shell: auto, powershell, pwsh, cmd, sh or bash. On Windows auto is
    PowerShell. elevated asks separately for sudo (Windows and POSIX).
    Never retry failed commands automatically: they may have partially run.
    Windows sudo must be enabled and uses the user's configured mode.
    Commands have closed stdin except POSIX sudo and Windows new-window mode.
    Windows elevated output may appear in a separate window;
    elevated commands wait until completion without a timeout.
    """
    context = {"command": command, "elevated": elevated}

    def result(status, **values):
        return json.dumps(dict(context, status=status, **values), ensure_ascii=False)

    try:
        if not command.strip() or "\x00" in command:
            raise ValueError("Command must be nonempty and contain no NUL characters")
        if not 1 <= timeout_seconds <= 86400:
            raise ValueError("timeout_seconds must be between 1 and 86400")
        if shell == "auto":
            shell = "powershell" if os.name == "nt" else "sh"
        if shell not in {"powershell", "pwsh", "cmd", "sh", "bash"}:
            raise ValueError("Unsupported shell")
        cwd = str(Path(working_directory).expanduser().resolve(strict=True))
        if not Path(cwd).is_dir():
            raise ValueError("Working directory is not a directory")
        argv = _shell_command(command, shell)
        context.update(working_directory=cwd, shell=shell)
        preview = json.dumps(command, ensure_ascii=False)
        if not _confirm(f"\nEjecutar en {json.dumps(cwd)} con {shell}:\n{preview}\n¿Autorizar este comando?"):
            return result("denied")
        if elevated:
            if not _confirm("¿Autorizar este mismo comando con permisos de administrador mediante sudo?"):
                return result("denied")
            if os.name == "nt":
                completed = _windows_elevated(argv, cwd)
                return result("completed" if completed.returncode == 0 else "failed",
                              exit_code=completed.returncode,
                              stdout=completed.stdout[-32000:], stderr=completed.stderr[-32000:],
                              output_truncated=max(len(completed.stdout), len(completed.stderr)) > 32000,
                              output_may_be_in_separate_window=True,
                              note="Windows sudo uses the configured mode. In new-window mode, command output is not captured. If sudo is disabled, enable it in Windows Settings before retrying.")
            sudo = shutil.which("sudo")
            if not sudo:
                raise ValueError("sudo is not installed")
            completed = subprocess.run([sudo, "--", *argv], cwd=cwd)
            return result("completed" if completed.returncode == 0 else "failed",
                          exit_code=completed.returncode, output_captured=False)
        completed = subprocess.run(
            argv, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True,
            text=True, errors="replace", timeout=timeout_seconds,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        return result("completed" if completed.returncode == 0 else "failed",
                      exit_code=completed.returncode,
                      stdout=completed.stdout[-32000:], stderr=completed.stderr[-32000:],
                      output_truncated=max(len(completed.stdout), len(completed.stderr)) > 32000)
    except subprocess.TimeoutExpired:
        return result("timeout", note="The shell timed out. Child processes may still be running; inspect before retrying.")
    except (OSError, ValueError) as error:
        return result("error", error=str(error))
