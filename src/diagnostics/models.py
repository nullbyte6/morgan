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
"""Typed telemetry. Sizes use binary GiB/MiB; missing values are never zero."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

HealthStatus = Literal["healthy", "warning", "critical", "unknown"]
Category = Literal["cpu", "memory", "storage", "security", "processes", "windows"]


class SourceError(BaseModel):
    source: str
    code: str


class Component(BaseModel):
    status: HealthStatus = "unknown"
    errors: list[SourceError] = Field(default_factory=list)
    unavailable: list[str] = Field(default_factory=list)


class ProcessUsage(BaseModel):
    pid: int
    name: str | None = None
    cpu_percent: float | None = None
    memory_mib: float | None = None
    observation: Literal["high_resource_usage"] | None = None


class CPUHealth(Component):
    usage_percent: float | None = None
    samples_percent: list[float] = Field(default_factory=list)
    sample_window_seconds: float = 0
    physical_cores: int | None = None
    logical_processors: int | None = None
    frequency_mhz: float | None = None
    per_core_percent: list[float] | None = None
    top_processes: list[ProcessUsage] = Field(default_factory=list)


class MemoryHealth(Component):
    total_gib: float | None = None
    available_gib: float | None = None
    used_gib: float | None = None
    used_percent: float | None = None
    samples_percent: list[float] = Field(default_factory=list)
    swap_total_gib: float | None = None
    swap_used_gib: float | None = None
    swap_percent: float | None = None
    top_processes: list[ProcessUsage] = Field(default_factory=list)


class VolumeHealth(BaseModel):
    drive: str
    filesystem: str | None = None
    total_gib: float | None = None
    used_gib: float | None = None
    free_gib: float | None = None
    used_percent: float | None = None


class PhysicalDisk(BaseModel):
    device_id: str
    media_type: str | None = None
    health_status: str | None = None
    operational_status: list[str] = Field(default_factory=list)
    temperature_c: float | None = None
    wear_percent: float | None = None
    power_on_hours: int | None = None
    read_errors_total: int | None = None
    write_errors_total: int | None = None
    read_errors_uncorrected: int | None = None
    write_errors_uncorrected: int | None = None
    reliability_available: bool = False


class DiskHealth(Component):
    volumes: list[VolumeHealth] = Field(default_factory=list)
    physical_disks: list[PhysicalDisk] = Field(default_factory=list)


class SecurityHealth(Component):
    antivirus_enabled: bool | None = None
    antispyware_enabled: bool | None = None
    realtime_protection_enabled: bool | None = None
    behavior_monitor_enabled: bool | None = None
    ioav_protection_enabled: bool | None = None
    nis_enabled: bool | None = None
    antivirus_signature_last_updated: datetime | None = None
    quick_scan_age_days: int | None = None
    full_scan_age_days: int | None = None
    defender_running_mode: str | None = None
    registered_antivirus: list[str] | None = None


class ProcessHealth(Component):
    total_count: int | None = None
    inspected_count: int = 0
    inaccessible_or_exited_count: int = 0
    top_cpu: list[ProcessUsage] = Field(default_factory=list)
    top_memory: list[ProcessUsage] = Field(default_factory=list)


class EventSummary(BaseModel):
    log: str
    provider: str
    event_id: int
    level: int
    count: int
    latest: datetime | None = None


class DeviceProblem(BaseModel):
    device_class: str | None = None
    error_code: int


class ServiceState(BaseModel):
    name: str
    state: str | None = None
    start_mode: str | None = None


class UpdateSummary(BaseModel):
    reboot_required: bool | None = None
    recent_history_count: int | None = None
    recent_failed_count: int | None = None
    last_install_date: datetime | None = None
    available_updates: int | None = None


class WindowsHealth(Component):
    version: str | None = None
    hostname: str | None = None
    architecture: str | None = None
    uptime_seconds: float | None = None
    last_boot: datetime | None = None
    events: list[EventSummary] = Field(default_factory=list)
    events_available: bool = False
    event_window_hours: int = 24
    events_examined: int = 0
    event_error_count: int = 0
    event_critical_count: int = 0
    events_truncated: bool = False
    event_groups_omitted: int = 0
    device_problems: list[DeviceProblem] = Field(default_factory=list)
    devices_available: bool = False
    devices_truncated: bool = False
    services: list[ServiceState] = Field(default_factory=list)
    updates: UpdateSummary | None = None


class HealthIssue(BaseModel):
    severity: Literal["warning", "critical"]
    category: Category
    code: str
    message: str
    evidence: dict[str, object] = Field(default_factory=dict)
    recommendation: str


class HealthReport(BaseModel):
    overall_status: HealthStatus = "unknown"
    score: int | None = Field(default=None, ge=0, le=100)
    timestamp: datetime
    scan_duration: float = 0
    mode: Literal["quick", "full"]
    scope: Literal["system", "disks", "security"] = "system"
    read_only: Literal[True] = True
    score_version: str = "1"
    assessed_components: list[Category] = Field(default_factory=list)
    incomplete: bool = True
    cpu: CPUHealth = Field(default_factory=CPUHealth)
    memory: MemoryHealth = Field(default_factory=MemoryHealth)
    disks: DiskHealth = Field(default_factory=DiskHealth)
    security: SecurityHealth = Field(default_factory=SecurityHealth)
    processes: ProcessHealth = Field(default_factory=ProcessHealth)
    windows: WindowsHealth = Field(default_factory=WindowsHealth)
    issues: list[HealthIssue] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
