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
"""Starting and stopping the local llama.cpp-omni server and the gateway in front of it."""
import glob
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

import psutil

from .config import load_config
from .lang import tr
from .voice_profiles import omni_model, omni_server_executable
from src.platforms import current_platform

HOST = "127.0.0.1"
PORT = 18766
HEALTH_URL = f"http://{HOST}:{PORT}/health"
WEBSOCKET_URL = f"ws://{HOST}:{PORT}/backend"
GATEWAY_HOST = "127.0.0.1"
GATEWAY_PORT = 18767
GATEWAY_URL = f"http://{GATEWAY_HOST}:{GATEWAY_PORT}"
MODEL_ID = "minicpm-o-4.5"
GATEWAY_MODULE = "src.init.omni_gateway"
SERVER_NAMES = {"llama-omni-server.exe", "llama-omni-server"}
START_SECONDS = 180
STOP_SECONDS = 10
MAX_CONTEXT_LENGTH = 16384


def _ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1):
            return True
    except OSError:
        return False


def omni_ready() -> bool:
    return _ready(HEALTH_URL)


def context_length() -> int:
    """The configured context length, held to what a 16 GB graphics card runs at full speed."""
    return min(load_config()["context_length"], MAX_CONTEXT_LENGTH)


def complete_text(prompt: str, max_tokens: int, timeout: float = 60) -> str:
    """One plain chat reply from the model, for the assistant's own short writing jobs."""
    request = urllib.request.Request(
        f"{GATEWAY_URL}/v1/chat/completions",
        data=json.dumps({"model": MODEL_ID, "max_tokens": max_tokens,
                         "messages": [{"role": "user", "content": prompt}]}).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return str(json.load(response)["choices"][0]["message"]["content"] or "").strip()


def gateway_ready() -> bool:
    return _ready(f"{GATEWAY_URL}/health")


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

    config = load_config()
    environment = {**os.environ, "OMNI_TTS_NGL": "99"}
    environment["PATH"] = os.pathsep.join(
        [str(executable.parent), *_runtime_directories(), environment.get("PATH", "")])
    process = subprocess.Popen(
        [str(executable), "-m", str(model), "--host", HOST, "--port", str(PORT),
         "-ngl", "99", "-c", str(context_length()), "--temp", str(config["temperature"])],
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


def stop_gateway() -> None:
    """Stop the gateway and the omni server it started, so the next start applies the settings."""
    found = []
    for process in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (process.info["name"] or "").casefold()
            command = " ".join(process.info["cmdline"] or ())
        except psutil.Error:
            continue
        if name in SERVER_NAMES or GATEWAY_MODULE in command:
            found.append(process)
    for process in found:
        try:
            process.terminate()
        except psutil.Error:
            continue
    _gone, alive = psutil.wait_procs(found, timeout=STOP_SECONDS)
    for process in alive:
        try:
            process.kill()
        except psutil.Error:
            continue
