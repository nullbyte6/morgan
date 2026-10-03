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
"""Starting and stopping the local llama.cpp-omni server that gives Arlo its voice."""
import glob
import os
import subprocess
import time
import urllib.request
from pathlib import Path

from .lang import tr
from .voice_profiles import omni_model, omni_server_executable
from src.platforms import current_platform

HOST = "127.0.0.1"
PORT = 18766
HEALTH_URL = f"http://{HOST}:{PORT}/health"
WEBSOCKET_URL = f"ws://{HOST}:{PORT}/backend"
CONTEXT_LENGTH = 4096
START_SECONDS = 180


def omni_ready() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=1):
            return True
    except OSError:
        return False


def _runtime_directories() -> list[str]:
    candidates = []
    hip_path = os.environ.get("HIP_PATH")
    if hip_path:
        candidates.append(Path(hip_path) / "bin")
    candidates.extend(Path(path) / "bin" for path in sorted(
        glob.glob(os.path.join(os.environ.get("ProgramFiles", ""), "AMD", "ROCm", "*")), reverse=True))
    return [str(path) for path in candidates if path.is_dir()]


def start_omni_server() -> subprocess.Popen | None:
    """Start the server unless one is already answering; None means an existing server is reused."""
    if omni_ready():
        return None
    executable = omni_server_executable()
    model = omni_model()
    if not executable.is_file():
        raise FileNotFoundError(tr("omni_server.server_not_found", path=executable))
    if not model.is_file():
        raise FileNotFoundError(tr("omni_server.model_not_found", path=model))

    environment = {**os.environ, "OMNI_TTS_NGL": "99"}
    environment["PATH"] = os.pathsep.join(
        [str(executable.parent), *_runtime_directories(), environment.get("PATH", "")])
    process = subprocess.Popen(
        [str(executable), "-m", str(model), "--host", HOST, "--port", str(PORT),
         "-ngl", "99", "-c", str(CONTEXT_LENGTH)],
        env=environment, cwd=str(executable.parent),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        close_fds=True, creationflags=current_platform().detached_flags)

    deadline = time.monotonic() + START_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(tr("omni_server.exited", code=process.returncode))
        if omni_ready():
            return process
        time.sleep(0.5)
    process.kill()
    raise TimeoutError(tr("omni_server.timeout"))


def stop_omni_server(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
