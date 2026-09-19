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

from src.init.lang import tr
from datetime import timezone

from .models import HealthIssue, HealthReport

CAPS = {"cpu": 10, "memory": 15, "storage": 40, "security": 25, "windows": 30,
        "processes": 0}
FIELDS = {"cpu": "cpu", "memory": "memory", "storage": "disks",
          "security": "security",
          "windows": "windows", "processes": "processes"}


def sustained(samples, threshold):
    return len(samples) >= 3 and all(value >= threshold for value in samples)


def evaluate(report: HealthReport) -> HealthReport:
    issues = []

    def issue(category, code, severity, message, evidence, recommendation):
        issues.append(
            HealthIssue(category=category, code=code, severity=severity,
                        message=message, evidence=evidence,
                        recommendation=recommendation))

    if sustained(report.cpu.samples_percent, 90):
        issue("cpu", "HIGH_CPU_USAGE", "warning",
              tr('scoring.cpu_remained_high_during_the_sample_window'),
              {"samples_percent": report.cpu.samples_percent,
               "window_seconds": report.cpu.sample_window_seconds},
              tr('scoring.review_the_busiest_processes_and_repeat_the_measurement_after_th'))
    if sustained(report.memory.samples_percent, 90):
        critical = sustained(report.memory.samples_percent, 97)
        issue("memory", "HIGH_MEMORY_USAGE",
              "critical" if critical else "warning",
              tr('scoring.ram_usage_remained_high_during_the_sample_window'),
              {"samples_percent": report.memory.samples_percent},
              tr('scoring.review_memory_heavy_applications_and_save_work_before_deciding_w'))
    for volume in report.disks.volumes:
        if volume.used_percent is not None and volume.used_percent >= 90:
            critical = volume.used_percent >= 97
            issue("storage",
                  "CRITICAL_DISK_SPACE" if critical else "LOW_DISK_SPACE",
                  "critical" if critical else "warning",
                  tr('scoring.a_volume_has_little_free_capacity'),
                  {"drive": volume.drive, "used_percent": volume.used_percent,
                   "free_gib": volume.free_gib},
                  tr('scoring.review_storage_usage_and_backups_choose_any_cleanup_separately_n'))
    for disk in report.disks.physical_disks:
        health = (disk.health_status or "").casefold()
        abnormal = [state for state in disk.operational_status if
                    state.casefold() in
                    {"degraded", "error", "stressed", "predictive failure",
                     "lost communication", "no contact"}]
        if health in {"warning", "unhealthy"} or abnormal:
            critical = health == "unhealthy" or any(
                state.casefold() == "error" for state in abnormal)
            issue("storage", "DISK_HEALTH_WARNING",
                  "critical" if critical else "warning",
                  tr('scoring.windows_reports_an_abnormal_physical_disk_state'),
                  {"device_id": disk.device_id,
                   "health_status": disk.health_status,
                   "operational_status": disk.operational_status},
                  tr('scoring.verify_current_backups_and_consult_the_disk_vendor_s_diagnostic'))
    security = report.security
    if "third_party_protection_not_verified" not in security.unavailable:
        for field, code in (("antivirus_enabled", "DEFENDER_DISABLED"),
                            ("realtime_protection_enabled",
                             "REALTIME_PROTECTION_DISABLED")):
            if getattr(security, field) is False:
                issue("security", code, "warning",
                      tr('scoring.a_defender_protection_flag_is_disabled'),
                      {field: False,
                       "running_mode": security.defender_running_mode},
                      tr('scoring.review_windows_security_and_confirm_which_antivirus_is_providing'))
        updated = security.antivirus_signature_last_updated
        if updated is not None and security.antivirus_enabled is True:
            age = (report.timestamp - updated.replace(
                tzinfo=updated.tzinfo or timezone.utc)).total_seconds() / 86400
            if age > 7:
                issue("security", "DEFENDER_SIGNATURES_OLD", "warning",
                      tr('scoring.defender_signatures_are_over_seven_days_old'),
                      {"age_days": round(age, 1)},
                      tr('scoring.review_signature_updates_in_windows_security'))
    windows = report.windows
    if windows.event_critical_count:
        issue("windows", "WINDOWS_CRITICAL_EVENTS", "warning",
              tr('scoring.windows_logged_critical_events_in_the_last_24_hours'),
              {"count": windows.event_critical_count,
               "truncated": windows.events_truncated},
              tr('scoring.review_the_grouped_event_ids_and_correlate_them_with_symptoms_a'))
    if windows.event_error_count >= 20:
        issue("windows", "WINDOWS_REPEATED_ERRORS", "warning",
              tr('scoring.windows_logged_repeated_errors_in_the_last_24_hours'),
              {"count": windows.event_error_count,
               "truncated": windows.events_truncated},
              tr('scoring.review_the_most_frequent_event_groups_before_deciding_whether_in'))
    problems = [device for device in windows.device_problems if
                device.error_code not in (0, 22)]
    if problems:
        issue("windows", "DEVICE_REPORTED_ERROR", "warning",
              tr('scoring.windows_reports_device_error_codes'),
              {"devices": [device.model_dump() for device in problems]},
              tr('scoring.inspect_the_reported_device_classes_in_device_manager_do_not_cha'))
    for service in windows.services:
        if service.name in {"EventLog", "BFE"} and (
                service.start_mode or "").casefold() == "disabled":
            issue("windows", "CORE_SERVICE_DISABLED", "warning",
                  tr('scoring.a_core_service_is_configured_as_disabled'),
                  service.model_dump(),
                  tr('scoring.review_the_service_configuration_with_the_system_administrator'))
    if windows.updates and windows.updates.recent_failed_count:
        issue("windows", "WINDOWS_UPDATE_HISTORY_FAILURE", "warning",
              tr('scoring.recent_local_update_history_contains_unsuccessful_operations'),
              windows.updates.model_dump(mode="json"),
              tr('scoring.review_windows_update_history_an_older_unsuccessful_operation_ma'))

    report.issues = sorted(issues, key=lambda item: item.severity != "critical")
    report.recommendations = list(
        dict.fromkeys(item.recommendation for item in report.issues))
    requested = list(FIELDS) if report.scope == "system" else [
        "storage" if report.scope == "disks" else "security"]
    report.assessed_components = [category for category in requested
                                  if getattr(report, FIELDS[
            category]).status != "unknown"]
    for item in issues:
        component = getattr(report, FIELDS[item.category])
        if component.status != "critical":
            component.status = item.severity
        if item.category not in report.assessed_components:
            report.assessed_components.append(item.category)
    report.incomplete = (len(report.assessed_components) < len(requested)
                         or any(
                getattr(report, FIELDS[category]).errors for category in
                requested))
    if not report.assessed_components:
        report.score = None
        report.overall_status = "unknown"
        return report
    deductions = {category: 0 for category in CAPS}
    for item in issues:
        deductions[item.category] += 25 if item.severity == "critical" else 10
    report.score = max(0, 100 - sum(
        min(CAPS[key], value) for key, value in deductions.items()))
    if report.score < 40 or any(item.severity == "critical" for item in issues):
        report.overall_status = "critical"
    elif issues or report.score < 90:
        report.overall_status = "warning"
    else:
        report.overall_status = "unknown" if report.incomplete else "healthy"
    return report
