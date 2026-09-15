"""Deterministic score v1, not a probability of failure or a security guarantee.

Start at 100 for observed components; deduct bounded category penalties:
CPU 10, memory 15, storage 40, security 25, Windows 30 (processes add none).
Warning/critical deductions are 10/25 unless overridden below. Multiple volumes,
events, or related symptoms cannot exceed their category cap. A critical issue
always makes overall status critical, independently of score. Otherwise scores
below 40 are critical, any issue or score below 90 is warning, and complete
observations without issues are healthy. Missing core checks make an otherwise
clean report unknown; score remains explicitly limited to observed components.
No observations => score=None. Optional metrics never deduct points.

CPU >=90% and memory >=90% must persist across at least 3 samples. Memory >=97%
is critical. Storage >=90% used warns, >=97% is critical. Physical status
Warning/Unhealthy or abnormal operational status is actionable; raw lifetime
error counters and temperatures alone have no universal failure threshold.
Defender disabled warns (passive/third-party configurations are unverified,
not penalized). Signatures older than 7 days warn. Scan ages never penalize.
Critical events warn once; >=20 errors warn once. Device codes except 22
(intentionally disabled) warn. Disabled EventLog/BFE and failed update history
warn; merely stopped demand-start services or uptime do not penalize.
"""

from datetime import timezone

from .models import HealthIssue, HealthReport

CAPS = {"cpu": 10, "memory": 15, "storage": 40, "security": 25, "windows": 30, "processes": 0}
FIELDS = {"cpu": "cpu", "memory": "memory", "storage": "disks", "security": "security",
          "windows": "windows", "processes": "processes"}


def sustained(samples, threshold):
    return len(samples) >= 3 and all(value >= threshold for value in samples)


def evaluate(report: HealthReport) -> HealthReport:
    issues = []

    def issue(category, code, severity, message, evidence, recommendation):
        issues.append(HealthIssue(category=category, code=code, severity=severity,
                                  message=message, evidence=evidence, recommendation=recommendation))

    if sustained(report.cpu.samples_percent, 90):
        issue("cpu", "HIGH_CPU_USAGE", "warning", "CPU remained high during the sample window.",
              {"samples_percent": report.cpu.samples_percent,
               "window_seconds": report.cpu.sample_window_seconds},
              "Review the busiest processes and repeat the measurement after the current workload finishes.")
    if sustained(report.memory.samples_percent, 90):
        critical = sustained(report.memory.samples_percent, 97)
        issue("memory", "HIGH_MEMORY_USAGE", "critical" if critical else "warning",
              "RAM usage remained high during the sample window.",
              {"samples_percent": report.memory.samples_percent},
              "Review memory-heavy applications and save work before deciding whether to close any.")
    for volume in report.disks.volumes:
        if volume.used_percent is not None and volume.used_percent >= 90:
            critical = volume.used_percent >= 97
            issue("storage", "CRITICAL_DISK_SPACE" if critical else "LOW_DISK_SPACE",
                  "critical" if critical else "warning", "A volume has little free capacity.",
                  {"drive": volume.drive, "used_percent": volume.used_percent, "free_gib": volume.free_gib},
                  "Review storage usage and backups; choose any cleanup separately. No files were removed.")
    for disk in report.disks.physical_disks:
        health = (disk.health_status or "").casefold()
        abnormal = [state for state in disk.operational_status if state.casefold() in
                    {"degraded", "error", "stressed", "predictive failure", "lost communication", "no contact"}]
        if health in {"warning", "unhealthy"} or abnormal:
            critical = health == "unhealthy" or any(state.casefold() == "error" for state in abnormal)
            issue("storage", "DISK_HEALTH_WARNING", "critical" if critical else "warning",
                  "Windows reports an abnormal physical disk state.",
                  {"device_id": disk.device_id, "health_status": disk.health_status,
                   "operational_status": disk.operational_status},
                  "Verify current backups and consult the disk vendor's diagnostic guidance.")
    security = report.security
    if "third_party_protection_not_verified" not in security.unavailable:
        for field, code in (("antivirus_enabled", "DEFENDER_DISABLED"),
                            ("realtime_protection_enabled", "REALTIME_PROTECTION_DISABLED")):
            if getattr(security, field) is False:
                issue("security", code, "warning", "A Defender protection flag is disabled.",
                      {field: False, "running_mode": security.defender_running_mode},
                      "Review Windows Security and confirm which antivirus is providing protection.")
        updated = security.antivirus_signature_last_updated
        if updated is not None and security.antivirus_enabled is True:
            age = (report.timestamp - updated.replace(tzinfo=updated.tzinfo or timezone.utc)).total_seconds() / 86400
            if age > 7:
                issue("security", "DEFENDER_SIGNATURES_OLD", "warning", "Defender signatures are over seven days old.",
                      {"age_days": round(age, 1)}, "Review signature updates in Windows Security.")
    windows = report.windows
    if windows.event_critical_count:
        issue("windows", "WINDOWS_CRITICAL_EVENTS", "warning", "Windows logged critical events in the last 24 hours.",
              {"count": windows.event_critical_count, "truncated": windows.events_truncated},
              "Review the grouped event IDs and correlate them with symptoms; a past event does not prove an ongoing fault.")
    if windows.event_error_count >= 20:
        issue("windows", "WINDOWS_REPEATED_ERRORS", "warning", "Windows logged repeated errors in the last 24 hours.",
              {"count": windows.event_error_count, "truncated": windows.events_truncated},
              "Review the most frequent event groups before deciding whether investigation is needed.")
    problems = [device for device in windows.device_problems if device.error_code not in (0, 22)]
    if problems:
        issue("windows", "DEVICE_REPORTED_ERROR", "warning", "Windows reports device error codes.",
              {"devices": [device.model_dump() for device in problems]},
              "Inspect the reported device classes in Device Manager; do not change drivers automatically.")
    for service in windows.services:
        if service.name in {"EventLog", "BFE"} and (service.start_mode or "").casefold() == "disabled":
            issue("windows", "CORE_SERVICE_DISABLED", "warning", "A core service is configured as disabled.",
                  service.model_dump(), "Review the service configuration with the system administrator.")
    if windows.updates and windows.updates.recent_failed_count:
        issue("windows", "WINDOWS_UPDATE_HISTORY_FAILURE", "warning", "Recent local update history contains unsuccessful operations.",
              windows.updates.model_dump(mode="json"),
              "Review Windows Update history; an older unsuccessful operation may already have been resolved.")

    report.issues = sorted(issues, key=lambda item: item.severity != "critical")
    report.recommendations = list(dict.fromkeys(item.recommendation for item in report.issues))
    requested = list(FIELDS) if report.scope == "system" else ["storage" if report.scope == "disks" else "security"]
    report.assessed_components = [category for category in requested
                                  if getattr(report, FIELDS[category]).status != "unknown"]
    for item in issues:
        component = getattr(report, FIELDS[item.category])
        if component.status != "critical":
            component.status = item.severity
        if item.category not in report.assessed_components:
            report.assessed_components.append(item.category)
    report.incomplete = (len(report.assessed_components) < len(requested)
                         or any(getattr(report, FIELDS[category]).errors for category in requested))
    if not report.assessed_components:
        report.score = None
        report.overall_status = "unknown"
        return report
    deductions = {category: 0 for category in CAPS}
    for item in issues:
        deductions[item.category] += 25 if item.severity == "critical" else 10
    report.score = max(0, 100 - sum(min(CAPS[key], value) for key, value in deductions.items()))
    if report.score < 40 or any(item.severity == "critical" for item in issues):
        report.overall_status = "critical"
    elif issues or report.score < 90:
        report.overall_status = "warning"
    else:
        report.overall_status = "unknown" if report.incomplete else "healthy"
    return report
