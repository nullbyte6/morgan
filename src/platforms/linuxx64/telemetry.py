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
"""Linux system telemetry read from sysfs, currently the graphics adapters."""

import shlex
import shutil
import subprocess
from pathlib import Path

from ..base import TelemetryError

VENDORS = {"0x1002": "AMD Radeon", "0x10de": "NVIDIA", "0x8086": "Intel"}


def _text(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _model(slot):
    lspci = shutil.which("lspci")
    if not lspci or not slot:
        return ""
    try:
        shown = subprocess.run([lspci, "-s", slot, "-mm"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    try:
        fields = shlex.split(shown.splitlines()[0]) if shown.strip() else []
    except ValueError:
        return ""
    fields = [field for field in fields if not field.startswith("-")]
    return f"{fields[2]} {fields[3]}" if len(fields) > 3 else ""


def graphics():
    adapters = []
    for card in sorted(Path("/sys/class/drm").glob("card[0-9]*")):
        if "-" in card.name:
            continue
        device = card / "device"
        vendor = _text(device / "vendor")
        if vendor not in VENDORS:
            continue
        slot = device.resolve().name
        driver = (device / "driver").resolve().name if (device / "driver").exists() else ""
        version = _text(Path("/sys/module") / driver / "version") if driver else ""
        adapters.append({"name": _model(slot) or VENDORS[vendor], "driver_version": version or driver,
                         "status": "OK"})
    if not adapters:
        raise TelemetryError("query_failed")
    return adapters


SOURCES = {"graphics": graphics}


def telemetry_query(source, full=False):
    return SOURCES[source]()
