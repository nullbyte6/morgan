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
"""The assistant's own health: Ollama, the main model, the GPU and PyTorch build, and the voice service."""
from __future__ import annotations

import json
import threading
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from importlib import metadata

from src.init.lang import tr

OLLAMA = "http://127.0.0.1:11434"
OK, WARNING, ERROR = "ok", "warning", "error"
GIGABYTE = 1024 ** 3

_lock = threading.Lock()
_model_loads: dict[str, tuple[float, datetime]] = {}


def record_model_load(model: str, response: dict) -> None:
    """Remember how long Ollama took to load model, from the load_duration of one of its replies."""
    nanoseconds = response.get("load_duration") if isinstance(response, dict) else None
    if isinstance(nanoseconds, (int, float)) and nanoseconds >= 50_000_000:
        with _lock:
            _model_loads[model] = (nanoseconds / 1e9, datetime.now())


def model_load(model: str) -> tuple[float, datetime] | None:
    with _lock:
        return _model_loads.get(model)


@dataclass(frozen=True)
class Check:
    area: str
    status: str
    summary: str
    details: list[str] = field(default_factory=list)
    fix: str = ""


def _ollama(path: str, timeout: float = 2) -> dict:
    with urllib.request.urlopen(OLLAMA + path, timeout=timeout) as response:
        return json.load(response)


def _gigabytes(size: int | float) -> str:
    return f"{size / GIGABYTE:.1f}"


def _assistant():
    try:
        from src.init.identity import get_assistant
        return get_assistant()
    except Exception:
        return None


def _model_name() -> str:
    name = getattr(_assistant(), "MODEL_NAME", None)
    if name:
        return name
    from src.init.brain import get_selected_model
    return get_selected_model()


def ollama_check() -> Check:
    try:
        version = _ollama("/api/version").get("version", "?")
        models = _ollama("/api/tags").get("models", [])
    except (OSError, ValueError) as error:
        return Check("ollama", ERROR, tr("health.ollama.down"), [str(error)], "start_ollama")
    return Check("ollama", OK, tr("health.ollama.running", version=version),
                 [tr("health.ollama.models", count=len(models))])


def model_check() -> Check:
    try:
        model = _model_name()
    except Exception as error:
        return Check("model", ERROR, tr("health.model.unknown"), [str(error)])
    from src.init.brain import is_cloud_model
    if is_cloud_model(model):
        return Check("model", OK, tr("health.model.cloud", model=model))
    load = model_load(model)
    details = [tr("health.model.load_time", seconds=f"{load[0]:.1f}", time=f"{load[1]:%H:%M}")] if load else []
    try:
        running = _ollama("/api/ps").get("models", [])
    except (OSError, ValueError) as error:
        return Check("model", ERROR, tr("health.model.unreachable", model=model), [str(error), *details])
    entry = next((item for item in running if item.get("name") in (model, f"{model}:latest")), None)
    if entry is None:
        return Check("model", WARNING, tr("health.model.idle", model=model), details, "load_model")
    size, vram = entry.get("size") or 0, entry.get("size_vram") or 0
    share = round(100 * vram / size) if size else 0
    details.insert(0, tr("health.model.memory", size=_gigabytes(size), vram=_gigabytes(vram)))
    if entry.get("context_length"):
        details.insert(1, tr("health.model.context", context=entry["context_length"]))
    status = OK if share >= 99 else WARNING
    return Check("model", status, tr("health.model.loaded", model=model, share=share), details)


def _torch_build() -> tuple[str, str]:
    """The installed PyTorch version and its build, read without importing it."""
    try:
        version = metadata.version("torch")
    except metadata.PackageNotFoundError:
        return "", "none"
    local = version.partition("+")[2].casefold()
    if local.startswith("rocm"):
        return version, "rocm"
    if local.startswith("cu"):
        return version, "cuda"
    if local == "cpu":
        return version, "cpu"
    return version, "unknown"


def gpu_check() -> Check:
    from src.diagnostics.queries import query, rows
    result = query("graphics")
    adapters = [row for row in rows(result.data) if isinstance(row, dict) and row.get("name")]
    version, build = _torch_build()
    details = [tr("health.gpu.adapter", name=row["name"], driver=row.get("driver_version") or "?")
               for row in adapters]
    details.append(tr(f"health.gpu.torch_{build}", version=version))
    vendors = " ".join(row["name"] for row in adapters).casefold()
    if result.error is not None and not adapters:
        return Check("gpu", WARNING, tr("health.gpu.unreadable"), details)
    if "nvidia" in vendors and build != "cuda":
        return Check("gpu", WARNING, tr("health.gpu.mismatch", vendor="NVIDIA", build="CUDA"), details)
    if ("amd" in vendors or "radeon" in vendors) and "nvidia" not in vendors and build != "rocm":
        return Check("gpu", WARNING, tr("health.gpu.mismatch", vendor="AMD", build="ROCm"), details)
    if build in ("cuda", "rocm"):
        return Check("gpu", OK, tr("health.gpu.accelerated", build="CUDA" if build == "cuda" else "ROCm"), details)
    return Check("gpu", WARNING, tr("health.gpu.cpu_only"), details)


def voice_check() -> Check:
    voice = getattr(_assistant(), "voice", None)
    if voice is None:
        return Check("voice", WARNING, tr("health.voice.not_started"))
    if not hasattr(voice, "_socket"):
        return Check("voice", OK, tr("health.voice.silent"))
    if getattr(voice, "_closed", False) or getattr(voice, "_error", None) is not None:
        error = getattr(voice, "_error", None)
        return Check("voice", ERROR, tr("health.voice.disconnected"), [str(error)] if error else [],
                     "restart_voice")
    info = getattr(voice, "service_info", {}) or {}
    details = []
    device = info.get("device") or {}
    if device:
        name = device.get("name") or tr("health.voice.processor")
        details.append(tr("health.voice.device", backend=device.get("backend", "?"), name=name))
    if info.get("load_seconds") is not None:
        details.append(tr("health.voice.load_time", seconds=f"{info['load_seconds']:.1f}"))
    status = WARNING if device.get("backend") == "CPU" else OK
    return Check("voice", status, tr("health.voice.connected"), details)


CHECKS = (ollama_check, model_check, gpu_check, voice_check)


def _start_ollama() -> None:
    from src.init.config import load_config
    from src.init.ollama_service import restart_ollama
    restart_ollama(load_config()["context_length"])


def _load_model() -> None:
    from src.init.brain import OLLAMA_KEEP_ALIVE
    model = _model_name()
    payload = json.dumps({"model": model, "prompt": "", "keep_alive": OLLAMA_KEEP_ALIVE,
                          "stream": False}).encode("utf-8")
    request = urllib.request.Request(OLLAMA + "/api/generate", data=payload, method="POST",
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=300) as response:
        record_model_load(model, json.load(response))


def _restart_voice() -> None:
    assistant = _assistant()
    if assistant is None or getattr(assistant, "voice", None) is None:
        raise RuntimeError(tr("health.voice.not_started"))
    from src.init.voice_client import VoiceClient
    previous = assistant.voice
    assistant._ensure_services()
    previous.close()
    assistant.voice = VoiceClient()
    assistant.voice.set_muted(getattr(previous, "_muted", False))


FIXES = {"start_ollama": _start_ollama, "load_model": _load_model, "restart_voice": _restart_voice}


def apply_fix(name: str) -> None:
    """Run one of the one-click repairs; raises with the reason when it fails."""
    FIXES[name]()


def report(checks: list[Check], checked_at: datetime) -> str:
    """The checks as Markdown with the version and system, ready to paste into a bug report."""
    import platform
    from src.init.brain import get_version
    from src.init.identity import get_assistant_name
    lines = [f"# {get_assistant_name()} · {tr('health.title')}", "",
             f"{get_version()} · {platform.platform()} · Python {platform.python_version()} · "
             f"{checked_at:%Y-%m-%d %H:%M:%S}"]
    for check in checks:
        lines += ["", f"## {tr(f'health.area.{check.area}')} · {check.status}", "", check.summary]
        lines += [f"- {detail}" for detail in check.details]
    return "\n".join(lines) + "\n"


def new_version_seen() -> bool:
    """Whether this is the first start of the running version, remembering it for the next start."""
    from src.init.brain import get_version
    from src.init.config import HOME_PATH
    path = HOME_PATH / "last_version"
    version = get_version()
    try:
        previous = path.read_text(encoding="utf-8").strip()
    except OSError:
        previous = ""
    if previous == version:
        return False
    try:
        path.write_text(version, encoding="utf-8")
    except OSError:
        return False
    return True


def collect() -> list[Check]:
    """Run every check, turning an unexpected failure into an error result instead of raising."""
    results = []
    for check in CHECKS:
        try:
            results.append(check())
        except Exception as error:
            area = check.__name__.removesuffix("_check")
            results.append(Check(area, ERROR, tr("health.failed"), [str(error)]))
    return results
