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
"""Local psutil telemetry sampled over short windows, with per-source isolation."""

import logging
import ntpath
import platform
import time
from datetime import datetime, timezone
from statistics import mean

import psutil

from src.platforms import current_platform

from .models import (
    CPUHealth, DiskHealth, MemoryHealth, ProcessHealth, ProcessUsage,
    SourceError, VolumeHealth, WindowsHealth,
)

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())
GIB = 1024 ** 3
MIB = 1024 ** 2


def read(component, source, function):
    """A failed metric must not discard other telemetry or expose exception text."""
    try:
        return function()
    except Exception as error:
        code = type(error).__name__
        if not any(item.source == source for item in component.errors):
            component.errors.append(SourceError(source=source, code=code))
        logger.debug("Telemetry %s unavailable: %s", source, code)
        return None


def resources(full=False):
    cpu, memory, processes = CPUHealth(), MemoryHealth(), ProcessHealth()
    cpu.physical_cores = read(cpu, "physical_cores", lambda: psutil.cpu_count(logical=False))
    cpu.logical_processors = read(cpu, "logical_processors", lambda: psutil.cpu_count(logical=True))
    frequency = read(cpu, "frequency", psutil.cpu_freq)
    cpu.frequency_mhz = frequency.current if frequency and frequency.current > 0 else None
    if cpu.frequency_mhz is None:
        cpu.unavailable.append("frequency_mhz")
    swap = read(memory, "swap", psutil.swap_memory)
    if swap is not None:
        memory.swap_total_gib = round(swap.total / GIB, 3)
        memory.swap_used_gib = round(swap.used / GIB, 3)
        memory.swap_percent = swap.percent
    else:
        memory.unavailable.append("swap")

    pids = read(processes, "process_count", psutil.pids)
    processes.total_count = len(pids) if pids is not None else None
    tracked = []

    def enumerate_processes():
        for process in psutil.process_iter():
            try:
                process.cpu_percent(None)
                tracked.append(process)
            except (psutil.Error, OSError):
                processes.inaccessible_or_exited_count += 1

    read(processes, "process_enumeration", enumerate_processes)
    read(cpu, "cpu_sample", lambda: psutil.cpu_percent(None, percpu=True))
    interval, count = (0.5, 5) if full else (0.4, 3)
    per_core_samples = []
    last_memory = None
    started = time.monotonic()
    for _ in range(count):
        time.sleep(interval)
        sample = read(cpu, "cpu_sample", lambda: psutil.cpu_percent(None, percpu=True))
        if sample:
            cpu.samples_percent.append(round(mean(sample), 2))
            per_core_samples.append(sample)
        measurement = read(memory, "memory_sample", psutil.virtual_memory)
        if measurement is not None:
            last_memory = measurement
            memory.samples_percent.append(measurement.percent)
    cpu.sample_window_seconds = round(time.monotonic() - started, 3)
    if cpu.samples_percent:
        cpu.usage_percent = round(mean(cpu.samples_percent), 2)
        cpu.per_core_percent = [round(mean(core), 2) for core in zip(*per_core_samples)]
        cpu.status = "healthy"
    if last_memory is not None:
        memory.total_gib = round(last_memory.total / GIB, 3)
        memory.used_gib = round(last_memory.used / GIB, 3)
        memory.available_gib = round(last_memory.available / GIB, 3)
        memory.used_percent = last_memory.percent
        memory.status = "healthy"

    usage = []
    for process in tracked:
        try:
            with process.oneshot():
                name = process.name()
                percent = process.cpu_percent(None)
                rss = process.memory_info().rss
            normalized = (round(min(100, percent / cpu.logical_processors), 2)
                          if cpu.logical_processors else None)
            usage.append(ProcessUsage(
                pid=process.pid, name=name, cpu_percent=normalized,
                memory_mib=round(rss / MIB, 2),
                observation="high_resource_usage" if (
                    (normalized is not None and normalized >= 25)
                    or (last_memory is not None and rss >= last_memory.total * 0.25)
                ) else None,
            ))
        except (psutil.Error, OSError):
            processes.inaccessible_or_exited_count += 1
    processes.inspected_count = len(usage)
    if processes.total_count is not None and usage:
        processes.status = "healthy"
    if processes.inaccessible_or_exited_count:
        processes.unavailable.append("some_process_metrics")
    processes.top_cpu = sorted(
        (item for item in usage if item.cpu_percent is not None),
        key=lambda item: item.cpu_percent, reverse=True)[:5]
    processes.top_memory = sorted(usage, key=lambda item: item.memory_mib, reverse=True)[:5]
    cpu.top_processes = processes.top_cpu
    memory.top_processes = processes.top_memory
    return cpu, memory, processes


def volumes():
    result = DiskHealth()
    partitions = read(result, "partitions", lambda: psutil.disk_partitions(all=False))
    seen = set()
    for index, partition in enumerate(partitions or []):
        if not partition.fstype or any(flag in partition.opts for flag in ("cdrom", "remote")):
            continue
        if partition.mountpoint in seen:
            continue
        seen.add(partition.mountpoint)
        drive = (ntpath.splitdrive(partition.mountpoint)[0] if current_platform().has_drive_letters
                 else f"volume_{index}")
        volume = VolumeHealth(drive=drive or f"volume_{index}", filesystem=partition.fstype)
        usage = read(result, f"volume:{volume.drive}", lambda: psutil.disk_usage(partition.mountpoint))
        if usage is not None:
            volume.total_gib = round(usage.total / GIB, 3)
            volume.used_gib = round(usage.used / GIB, 3)
            volume.free_gib = round(usage.free / GIB, 3)
            volume.used_percent = usage.percent
        result.volumes.append(volume)
    if any(volume.used_percent is not None for volume in result.volumes):
        result.status = "healthy"
    return result


def windows_baseline():
    result = WindowsHealth()
    if not current_platform().telemetry_sources:
        result.errors.append(SourceError(source="windows", code="unsupported"))
        return result
    result.version = platform.version()
    result.hostname = platform.node()
    result.architecture = platform.machine()
    boot = read(result, "boot_time", psutil.boot_time)
    if boot is not None:
        result.last_boot = datetime.fromtimestamp(boot, timezone.utc)
        result.uptime_seconds = max(0, time.time() - boot)
    return result
