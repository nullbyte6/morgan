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
"""Restarting the local Ollama server so a new context length applies."""
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

import psutil

from .lang import tr

VERSION_URL = "http://127.0.0.1:11434/api/version"
SERVER_NAMES = {"ollama.exe", "ollama"}
PROCESS_NAMES = SERVER_NAMES | {"ollama app.exe"}
STOP_SECONDS = 10
START_SECONDS = 30


def _processes() -> list[psutil.Process]:
    found = []
    for process in psutil.process_iter(["name"]):
        try:
            if (process.info["name"] or "").casefold() in PROCESS_NAMES:
                found.append(process)
        except psutil.Error:
            continue
    return found


def ollama_executable() -> Path | None:
    """The Ollama server program, taken from the running one, the PATH or the usual install folders."""
    for process in _processes():
        try:
            executable = Path(process.exe())
        except psutil.Error:
            continue
        if executable.name.casefold() in SERVER_NAMES:
            return executable
    found = shutil.which("ollama")
    if found:
        return Path(found)
    for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("ProgramFiles")):
        if base:
            for candidate in (Path(base) / "Programs" / "Ollama" / "ollama.exe", Path(base) / "Ollama" / "ollama.exe"):
                if candidate.is_file():
                    return candidate
    return None


def ollama_ready() -> bool:
    try:
        with urllib.request.urlopen(VERSION_URL, timeout=1):
            return True
    except OSError:
        return False


def restart_ollama(context_length: int) -> None:
    """Stop every Ollama process and start the server again with the given OLLAMA_CONTEXT_LENGTH."""
    executable = ollama_executable()
    if executable is None:
        raise FileNotFoundError(tr("ui.restart_ollama_missing"))
    processes = _processes()
    for process in processes:
        try:
            process.terminate()
        except psutil.Error:
            continue
    _gone, alive = psutil.wait_procs(processes, timeout=STOP_SECONDS)
    for process in alive:
        try:
            process.kill()
        except psutil.Error:
            continue
    psutil.wait_procs(alive, timeout=STOP_SECONDS)
    options = {}
    if os.name == "nt":
        options["creationflags"] = (subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
                                    | subprocess.CREATE_NEW_PROCESS_GROUP)
    subprocess.Popen(
        [str(executable), "serve"], env={**os.environ, "OLLAMA_CONTEXT_LENGTH": str(context_length)},
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, **options)
    deadline = time.monotonic() + START_SECONDS
    while time.monotonic() < deadline:
        if ollama_ready():
            return
        time.sleep(0.5)
    raise TimeoutError(tr("ui.restart_ollama_timeout"))
