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
"""Validate and merge bounded PowerShell results without leaking raw payloads."""

from src.init.lang import tr
from .models import (
    DeviceProblem, EventSummary, PhysicalDisk, SecurityHealth, ServiceState,
    SourceError, UpdateSummary,
)
from .powershell import rows
from .telemetry import read


def accept(component, source, result, consumer):
    if result.error:
        component.errors.append(result.error)
        return
    if result.data is None:
        component.unavailable.append(source)
        return
    read(component, source, lambda: consumer(result.data))


def security(results):
    result = SecurityHealth()

    def defender(data):
        values = SecurityHealth.model_validate(data)
        for field in SecurityHealth.model_fields.keys() - {"status", "errors", "unavailable"}:
            setattr(result, field, getattr(values, field))

    accept(result, "defender", results["defender"], defender)

    def antivirus(data):
        values = rows(data)
        if not all(isinstance(item, str) for item in values):
            raise ValueError(tr('windows.unexpected_antivirus_data'))
        result.registered_antivirus = values

    accept(result, "antivirus", results["antivirus"], antivirus)
    for field in ("antivirus_enabled", "realtime_protection_enabled", "antivirus_signature_last_updated"):
        if getattr(result, field) is None:
            result.unavailable.append(field)
    if result.antivirus_enabled is not None and result.realtime_protection_enabled is not None:
        result.status = "healthy"
    mode = (result.defender_running_mode or "").casefold()
    others = [name for name in result.registered_antivirus or []
              if "defender" not in name.casefold()]
    if "passive" in mode or "edr" in mode or (others and result.antivirus_enabled is not True):
        result.status = "unknown"
        result.unavailable.append("third_party_protection_not_verified")
    return result


def physical_disks(result, queries):
    def physical(data):
        for item in rows(data):
            disk = read(result, "physical_disk_record", lambda: PhysicalDisk.model_validate(item))
            if disk is not None:
                result.physical_disks.append(disk)

    accept(result, "physical_disks", queries["physical_disks"], physical)

    def reliability(data):
        by_id = {disk.device_id: disk for disk in result.physical_disks}
        for item in rows(data):
            disk = by_id.get(str(item.get("device_id")))
            if disk is None:
                continue
            if item.get("unavailable"):
                result.unavailable.append(f"reliability:{disk.device_id}")
                continue
            values = read(result, "reliability_record", lambda: PhysicalDisk.model_validate(item))
            if values is not None:
                fields = ("temperature_c", "wear_percent", "power_on_hours", "read_errors_total",
                          "write_errors_total", "read_errors_uncorrected", "write_errors_uncorrected")
                for field in fields:
                    setattr(disk, field, getattr(values, field))
                disk.reliability_available = any(getattr(values, field) is not None for field in fields)
                if not disk.reliability_available:
                    result.unavailable.append(f"reliability:{disk.device_id}")

    accept(result, "reliability", queries["reliability"], reliability)
    for disk in result.physical_disks:
        if (disk.health_status or "").casefold() not in {"healthy", "warning", "unhealthy"}:
            result.unavailable.append(f"physical_health:{disk.device_id}")
    if result.status == "unknown" and any(
            (disk.health_status or "").casefold() in {"healthy", "warning", "unhealthy"}
            for disk in result.physical_disks):
        result.status = "healthy"
    return result


def windows_details(result, queries, full):
    def events(data):
        result.events = [EventSummary.model_validate(item) for item in rows(data.get("groups"))]
        result.events_examined = int(data["examined"])
        result.event_critical_count = int(data["critical_count"])
        result.event_error_count = int(data["error_count"])
        result.events_truncated = bool(data["truncated"])
        result.event_groups_omitted = int(data["groups_omitted"])
        failed = rows(data.get("failed_logs"))
        result.events_available = len(failed) < 2
        for log in failed:
            result.errors.append(SourceError(source=f"events:{log}", code="query_failed"))
        if result.events_available:
            result.status = "healthy"

    source = "events_full" if full else "events_quick"
    accept(result, source, queries[source], events)
    if not full:
        result.unavailable.extend(["devices_not_requested", "services_not_requested", "updates_not_requested"])
        return result

    def devices(data):
        result.device_problems = [DeviceProblem.model_validate(item) for item in rows(data["items"])]
        result.devices_truncated = bool(data["truncated"])
        result.devices_available = True

    def services(data):
        result.services = [ServiceState.model_validate(item) for item in rows(data)]

    def updates(data):
        result.updates = UpdateSummary.model_validate(data)
        result.unavailable.append("available_updates_not_queried")

    for source, consumer in (("devices", devices), ("services", services), ("updates", updates)):
        accept(result, source, queries[source], consumer)
    return result
