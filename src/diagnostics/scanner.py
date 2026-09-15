"""Orchestrate independent read-only sources with bounded concurrency."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import time
from typing import Literal

from . import powershell, telemetry, windows
from .models import HealthReport, SourceError
from .scoring import evaluate


class SystemHealthScanner:
    """No agent, model, user-config, persistent logging or repair dependencies."""

    def quick_scan(self) -> HealthReport:
        return self._scan("quick", "system")

    def full_scan(self) -> HealthReport:
        return self._scan("full", "system")

    def disk_scan(self, mode: Literal["quick", "full"] = "full") -> HealthReport:
        return self._scan(mode, "disks")

    def security_scan(self) -> HealthReport:
        return self._scan("quick", "security")

    def _scan(self, mode, scope):
        if mode not in ("quick", "full"):
            raise ValueError("mode must be quick or full")
        started = time.monotonic()
        full = mode == "full"
        report = HealthReport(timestamp=datetime.now(timezone.utc), mode=mode, scope=scope)
        queries = []
        if scope in ("system", "security"):
            queries.extend(["defender", "antivirus"])
        if full and scope in ("system", "disks"):
            queries.extend(["physical_disks", "reliability"])
        if scope == "system":
            queries.append("events_full" if full else "events_quick")
            if full:
                queries.extend(["devices", "services", "updates"])
        results = {}
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="health") as pool:
            resources = pool.submit(telemetry.resources, full) if scope == "system" else None
            if scope in ("system", "disks"):
                value = telemetry.read(report.disks, "volumes", telemetry.volumes)
                if value is not None:
                    report.disks = value
            if scope == "system":
                value = telemetry.read(report.windows, "windows_inventory", telemetry.windows_baseline)
                if value is not None:
                    report.windows = value
            if resources is not None:
                try:
                    report.cpu, report.memory, report.processes = resources.result()
                except Exception as error:
                    for component in (report.cpu, report.memory, report.processes):
                        component.errors.append(SourceError(source="resources", code=type(error).__name__))
            futures = {source: pool.submit(powershell.query, source, full=full) for source in queries}
            for source, future in futures.items():
                try:
                    results[source] = future.result()
                except Exception as error:
                    results[source] = powershell.QueryResult(
                        error=SourceError(source=source, code=type(error).__name__))
        if scope in ("system", "security"):
            report.security = windows.security(results)
        if full and scope in ("system", "disks"):
            report.disks = windows.physical_disks(report.disks, results)
        elif scope in ("system", "disks"):
            report.disks.unavailable.append("physical_disks_and_reliability_not_requested")
        if scope == "system":
            report.windows = windows.windows_details(report.windows, results, full)
        for category, field in (("cpu", "cpu"), ("memory", "memory"), ("storage", "disks"),
                                ("security", "security"), ("processes", "processes"), ("windows", "windows")):
            if scope != "system" and category != ("storage" if scope == "disks" else "security"):
                getattr(report, field).unavailable.append("not_requested")
        report = evaluate(report)
        report.scan_duration = round(time.monotonic() - started, 3)
        return report
