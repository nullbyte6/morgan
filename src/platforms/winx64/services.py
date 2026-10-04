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
"""Service startup, installer handoff, priorities and memory trimming on Windows."""

from contextlib import contextmanager
import ctypes
import os
from pathlib import Path
import shutil
import subprocess

INSTALLER_SWITCHES = ("/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS")


def service_launchers(name):
    return list(dict.fromkeys((f"{name}-services.ps1", "morgan-services.ps1")))


def service_command(script, voice):
    from src.init.lang import tr
    powershell = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
    if powershell is None:
        raise RuntimeError(tr("startup.powershell_missing"))
    return [powershell, "-NoLogo", "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "Bypass", "-File", str(script), "-NoConsole",
            *(() if voice else ("-NoVoice",))]


@contextmanager
def unbundled_libraries(bundle):
    ctypes.windll.kernel32.SetDllDirectoryW(None)
    try:
        yield
    finally:
        ctypes.windll.kernel32.SetDllDirectoryW(str(bundle))


def installed_executable():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Morgan\Installer") as key:
            return Path(winreg.QueryValueEx(key, "InstallPath")[0]) / "Morgan.exe"
    except OSError:
        return None


def _quoted(value):
    return "'" + value.replace("'", "''") + "'"


def run_installer_after_exit(setup, command, directory, environment):
    arguments = ", ".join(_quoted(argument) for argument in command[1:]) or "@()"
    script = "; ".join((
        "$ErrorActionPreference = 'SilentlyContinue'",
        f"Wait-Process -Id {os.getpid()}",
        f"$setup = {_quoted(str(setup))}",
        "Start-Process -FilePath $setup -ArgumentList " + ", ".join(map(_quoted, INSTALLER_SWITCHES)) + " -Wait",
        "Remove-Item -LiteralPath $setup -Force",
        f"$arguments = @({arguments})",
        f"if ($arguments.Count) {{ Start-Process -FilePath {_quoted(command[0])} -ArgumentList $arguments "
        f"-WorkingDirectory {_quoted(str(directory))} }} "
        f"else {{ Start-Process -FilePath {_quoted(command[0])} -WorkingDirectory {_quoted(str(directory))} }}",
    ))
    powershell = (Path(os.environ.get("SystemRoot", r"C:\Windows"))
                  / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")
    subprocess.Popen(
        [str(powershell) if powershell.is_file() else "powershell.exe",
         "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        env=environment, cwd=str(setup.parent), stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)


def raise_priority(process):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    if process:
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), 0x00008000)
    else:
        kernel32.GetCurrentThread.restype = ctypes.c_void_p
        kernel32.SetThreadPriority.argtypes = [ctypes.c_void_p, ctypes.c_int]
        kernel32.SetThreadPriority(kernel32.GetCurrentThread(), 2)


def trim_memory():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.EmptyWorkingSet.argtypes = [ctypes.c_void_p]
    psapi.EmptyWorkingSet.restype = ctypes.c_int
    if not psapi.EmptyWorkingSet(kernel32.GetCurrentProcess()):
        raise ctypes.WinError(ctypes.get_last_error())
