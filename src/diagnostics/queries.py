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
"""Allowlisted, bounded local system queries answered by the active platform."""

from src.init.lang import tr
import logging
import subprocess
from dataclasses import dataclass

from src.platforms import TelemetryError, current_platform

from .models import SourceError

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

SOURCES = ("defender", "antivirus", "physical_disks", "reliability", "events_quick",
           "events_full", "devices", "services", "updates", "graphics")


@dataclass
class QueryResult:
    data: object = None
    error: SourceError | None = None


def query(source: str, *, full: bool = False) -> QueryResult:
    """Run exactly one approved query with an 8s/15s timeout; no elevation."""
    if source not in SOURCES:
        raise ValueError(tr('powershell.unknown_telemetry_source'))
    platform = current_platform()
    if source not in platform.telemetry_sources:
        return QueryResult(error=SourceError(source=source, code="unsupported"))
    try:
        return QueryResult(data=platform.telemetry_query(source, full))
    except TelemetryError as error:
        logger.debug("Telemetry %s failed: code=%s", source, error.code)
        return QueryResult(error=SourceError(source=source, code=error.code))
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        code = "timeout" if isinstance(error, subprocess.TimeoutExpired) else type(error).__name__
        logger.debug("Telemetry %s unavailable: %s", source, code)
        return QueryResult(error=SourceError(source=source, code=code))


def rows(data):
    """PowerShell unwraps singleton arrays; normalize without inventing objects."""
    if data is None:
        return []
    return data if isinstance(data, list) else [data]
