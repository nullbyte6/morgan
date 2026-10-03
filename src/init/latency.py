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
"""Lightweight per-turn latency log: end of user speech to first audible audio."""
import logging
import threading
import time

logger = logging.getLogger("assistant.latency")
_lock = threading.Lock()
_marks = {}


def begin(stage="speech_end"):
    """Start timing a new spoken turn, replacing any unfinished one."""
    with _lock:
        _marks.clear()
        _marks[stage] = time.monotonic()
    logger.info("Voice latency: %s", stage)


def discard():
    """Forget the current turn, used when a turn does not come from speech."""
    with _lock:
        _marks.clear()


def mark(stage):
    """Record the first occurrence of a stage in the current spoken turn."""
    now = time.monotonic()
    with _lock:
        if not _marks or stage in _marks:
            return
        previous_stage, previous = max(_marks.items(), key=lambda item: item[1])
        first_stage, first = min(_marks.items(), key=lambda item: item[1])
        _marks[stage] = now
    logger.info("Voice latency: %s +%d ms after %s, %d ms after %s", stage,
                (now - previous) * 1000, previous_stage, (now - first) * 1000,
                first_stage)
