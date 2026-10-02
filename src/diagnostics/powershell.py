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
"""Allowlisted, bounded local Windows queries. Never accepts command text."""

from src.init.lang import tr
import base64
import json
import logging
import os
import subprocess
from dataclasses import dataclass

from .models import SourceError

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

DEFENDER = r"""
$s = Get-MpComputerStatus -ErrorAction Stop
[pscustomobject]@{
    antivirus_enabled = $s.AntivirusEnabled
    antispyware_enabled = $s.AntispywareEnabled
    realtime_protection_enabled = $s.RealTimeProtectionEnabled
    behavior_monitor_enabled = $s.BehaviorMonitorEnabled
    ioav_protection_enabled = $s.IoavProtectionEnabled
    nis_enabled = $s.NISEnabled
    antivirus_signature_last_updated = $(if ($s.AntivirusSignatureLastUpdated) {
        $s.AntivirusSignatureLastUpdated.ToUniversalTime().ToString('o') } else { $null })
    quick_scan_age_days = $(if ($s.QuickScanAge -lt 65535) { $s.QuickScanAge } else { $null })
    full_scan_age_days = $(if ($s.FullScanAge -lt 65535) { $s.FullScanAge } else { $null })
    defender_running_mode = $s.AMRunningMode
}
"""

PHYSICAL_DISKS = r"""
$items = @(Get-PhysicalDisk -ErrorAction Stop)
@($items | ForEach-Object {
    [pscustomobject]@{
        device_id = [string]$_.DeviceId
        media_type = [string]$_.MediaType
        health_status = [string]$_.HealthStatus
        operational_status = @($_.OperationalStatus | ForEach-Object { [string]$_ })
    }
})
"""

RELIABILITY = r"""
@(Get-PhysicalDisk -ErrorAction Stop | ForEach-Object {
    $disk = $_
    try {
        $r = $disk | Get-StorageReliabilityCounter -ErrorAction Stop
        [pscustomobject]@{
            device_id = [string]$disk.DeviceId
            temperature_c = $r.Temperature
            wear_percent = $r.Wear
            power_on_hours = $r.PowerOnHours
            read_errors_total = $r.ReadErrorsTotal
            write_errors_total = $r.WriteErrorsTotal
            read_errors_uncorrected = $r.ReadErrorsUncorrected
            write_errors_uncorrected = $r.WriteErrorsUncorrected
        }
    } catch {
        [pscustomobject]@{ device_id = [string]$disk.DeviceId; unavailable = $true }
    }
})
"""

EVENTS = r"""
$events = @()
$failed = @()
$truncated = $false
foreach ($log in @('System', 'Application')) {
    try {
        $batch = @(Get-WinEvent -FilterHashtable @{
            LogName = $log; Level = @(1, 2); StartTime = (Get-Date).AddHours(-24)
        } -MaxEvents EVENT_FETCH_LIMIT -ErrorAction Stop)
        if ($batch.Count -gt EVENT_LIMIT) { $truncated = $true }
        $events += @($batch | Select-Object -First EVENT_LIMIT)
    } catch {
        if ($_.FullyQualifiedErrorId -notlike 'NoMatchingEventsFound*') { $failed += $log }
    }
}
$groups = @($events | Group-Object LogName, ProviderName, Id, Level |
    Sort-Object Count -Descending)
[pscustomobject]@{
    failed_logs = $failed
    examined = $events.Count
    critical_count = @($events | Where-Object { $_.Level -eq 1 }).Count
    error_count = @($events | Where-Object { $_.Level -eq 2 }).Count
    truncated = $truncated
    groups_omitted = [Math]::Max(0, $groups.Count - 20)
    groups = @($groups | Select-Object -First 20 | ForEach-Object {
        $last = $_.Group | Sort-Object TimeCreated -Descending | Select-Object -First 1
        [pscustomobject]@{
            log = $last.LogName; provider = $last.ProviderName; event_id = $last.Id
            level = $last.Level; count = $_.Count
            latest = $last.TimeCreated.ToUniversalTime().ToString('o')
        }
    })
}
"""

DEVICES = r"""
$items = @(Get-CimInstance Win32_PnPEntity -Filter 'ConfigManagerErrorCode <> 0' -ErrorAction Stop)
[pscustomobject]@{
    truncated = ($items.Count -gt 30)
    items = @($items | Select-Object -First 30 | ForEach-Object {
        [pscustomobject]@{ device_class = $_.PNPClass; error_code = $_.ConfigManagerErrorCode }
    })
}
"""

SERVICES = r"""
@(Get-CimInstance Win32_Service -Filter "Name='wuauserv' OR Name='WinDefend' OR Name='EventLog' OR Name='BFE'" -ErrorAction Stop |
    ForEach-Object { [pscustomobject]@{
        name = $_.Name; state = $_.State; start_mode = $_.StartMode
    } })
"""

UPDATES = r"""
# QueryHistory only reads local history; do not call Search/Download/Install.
$session = New-Object -ComObject Microsoft.Update.Session
$searcher = $session.CreateUpdateSearcher()
$count = [Math]::Min(20, $searcher.GetTotalHistoryCount())
$history = @()
if ($count -gt 0) { $history = @($searcher.QueryHistory(0, $count)) }
$recent = @($history | Where-Object { $_.Date -ge (Get-Date).AddDays(-30) })
$last = $history | Where-Object { $_.Operation -eq 1 -and $_.ResultCode -eq 2 } |
    Sort-Object Date -Descending | Select-Object -First 1
[pscustomobject]@{
    reboot_required = ((Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired') -or
        (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending'))
    recent_history_count = $recent.Count
    recent_failed_count = @($recent | Where-Object { $_.ResultCode -in @(3,4,5) }).Count
    last_install_date = $(if ($last) { $last.Date.ToUniversalTime().ToString('o') } else { $null })
}
"""

GRAPHICS = r"""
@(Get-CimInstance Win32_VideoController -ErrorAction Stop | ForEach-Object {
    [pscustomobject]@{ name = [string]$_.Name; driver_version = [string]$_.DriverVersion; status = [string]$_.Status }
})
"""

SCRIPTS = {
    "defender": DEFENDER,
    "antivirus": "@(Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntivirusProduct -ErrorAction Stop | Select-Object -ExpandProperty displayName)",
    "physical_disks": PHYSICAL_DISKS,
    "reliability": RELIABILITY,
    "events_quick": EVENTS.replace("EVENT_FETCH_LIMIT", "101").replace("EVENT_LIMIT", "100"),
    "events_full": EVENTS.replace("EVENT_FETCH_LIMIT", "501").replace("EVENT_LIMIT", "500"),
    "devices": DEVICES,
    "services": SERVICES,
    "updates": UPDATES,
    "graphics": GRAPHICS,
}


@dataclass
class QueryResult:
    data: object = None
    error: SourceError | None = None


def query(source: str, *, full: bool = False) -> QueryResult:
    """Run exactly one approved query with an 8s/15s timeout; no elevation."""
    if source not in SCRIPTS:
        raise ValueError(tr('powershell.unknown_telemetry_source'))
    if os.name != "nt":
        return QueryResult(error=SourceError(source=source, code="unsupported"))
    script = (
        "$ErrorActionPreference = 'Stop'\n"
        "$ProgressPreference = 'SilentlyContinue'\n"
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()\n"
        "$result = & {\n" + SCRIPTS[source] + "\n}\n"
        "ConvertTo-Json -InputObject $result -Depth 6 -Compress\n"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
             "-EncodedCommand", base64.b64encode(script.encode("utf-16-le")).decode("ascii")],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=15 if full else 8, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode:
            code = "access_denied" if "UnauthorizedAccess" in result.stderr else "query_failed"
            logger.debug("Telemetry %s failed: exit=%s code=%s", source, result.returncode, code)
            return QueryResult(error=SourceError(source=source, code=code))
        if len(result.stdout) > 262144:
            return QueryResult(error=SourceError(source=source, code="output_limit"))
        return QueryResult(data=json.loads(result.stdout.lstrip("\ufeff")))
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        code = "timeout" if isinstance(error, subprocess.TimeoutExpired) else type(error).__name__
        logger.debug("Telemetry %s unavailable: %s", source, code)
        return QueryResult(error=SourceError(source=source, code=code))


def rows(data):
    """PowerShell unwraps singleton arrays; normalize without inventing objects."""
    if data is None:
        return []
    return data if isinstance(data, list) else [data]
