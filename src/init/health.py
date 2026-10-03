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
"""The assistant's own health: the omni model and its gateway, the GPU and PyTorch build, and the voice service."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from importlib import metadata

from src.init.lang import tr

OK, WARNING, ERROR = "ok", "warning", "error"


@dataclass(frozen=True)
class Check:
    area: str
    status: str
    summary: str
    details: list[str] = field(default_factory=list)


def _assistant():
    try:
        from src.init.identity import get_assistant
        return get_assistant()
    except Exception:
        return None


def omni_check() -> Check:
    from src.init.omni_server import MODEL_ID, context_length, gateway_ready, omni_ready
    if not gateway_ready():
        return Check("omni", ERROR, tr("health.omni.down"))
    status = OK if omni_ready() else WARNING
    return Check("omni", status, tr("health.omni.running", model=MODEL_ID),
                 [tr("health.omni.context", context=context_length())])


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
        return Check("voice", ERROR, tr("health.voice.disconnected"), [str(error)] if error else [])
    info = getattr(voice, "service_info", {}) or {}
    details = []
    device = info.get("device") or {}
    if device:
        name = device.get("name") or tr("health.voice.processor")
        details.append(tr("health.voice.device", backend=device.get("backend", "?"), name=name))
    status = WARNING if device.get("backend") == "CPU" else OK
    return Check("voice", status, tr("health.voice.connected"), details)


CHECKS = (omni_check, gpu_check, voice_check)


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
