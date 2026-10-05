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
"""Thin typed tools exposed through the existing Pydantic AI registry."""

from src.init.lang import tr
from src.init.brain import kill_self
from typing import Literal

from .models import HealthReport
from .scanner import SystemHealthScanner


def check_system_health(mode: Literal["quick", "full"] = "quick") -> HealthReport:
    """Check PC health or unusual resource use with local read-only telemetry.

    Use quick for everyday health questions; full only for an explicit complete
    diagnosis. Returns measured CPU/RAM, disk capacity, processes, Defender and
    Windows observations, deterministic score and unavailable checks. Full also
    reads physical disk reliability, devices, services and local update history.
    Does not run antivirus scans, repair, modify settings or stop processes.
    """
    scanner = SystemHealthScanner()
    if mode == "quick":
        return scanner.quick_scan()
    if mode == "full":
        return scanner.full_scan()
    raise ValueError(tr('scanner.mode_must_be_quick_or_full'))


def check_disk_health(mode: Literal["quick", "full"] = "full") -> HealthReport:
    """Inspect storage only: quick checks volume space; full adds physical health
    and available reliability counters. Use for disk/SSD health questions.
    Missing SMART is unknown, not evidence of damage. Read-only; no repair.
    """
    return SystemHealthScanner().disk_scan(mode)


def check_security_health() -> HealthReport:
    """Read Defender status, signature age and registered antivirus products.
    Use for PC security/protection questions. This is a status check, not a
    malware scan; other antivirus registration does not prove active protection.
    Never changes Defender settings or starts an antivirus scan.
    """
    return SystemHealthScanner().security_scan()
