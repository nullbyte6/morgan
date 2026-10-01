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
"""Date arithmetic behind the week, month and year calendar views."""
from calendar import monthrange
from datetime import date, timedelta

WEEK, MONTH, YEAR = "week", "month", "year"
MODES = (WEEK, MONTH, YEAR)


def week_start(day: date, first_weekday: int) -> date:
    """The first day of the week containing day; weekdays count from Monday as 0."""
    return day - timedelta(days=(day.weekday() - first_weekday) % 7)


def week_days(day: date, first_weekday: int) -> list[date]:
    start = week_start(day, first_weekday)
    return [start + timedelta(days=offset) for offset in range(7)]


def month_grid(year: int, month: int, first_weekday: int) -> list[list[date]]:
    """The weeks needed to show a month, padded with the neighbouring months' days."""
    first = date(year, month, 1)
    start = week_start(first, first_weekday)
    rows = -(-((first - start).days + monthrange(year, month)[1]) // 7)
    return [[start + timedelta(days=row * 7 + column) for column in range(7)] for row in range(rows)]


def shift_month(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(day.day, monthrange(year, month)[1]))


def shift(day: date, mode: str, steps: int) -> date:
    """Move day by whole weeks, months or years."""
    if mode == WEEK:
        return day + timedelta(weeks=steps)
    if mode == MONTH:
        return shift_month(day, steps)
    return shift_month(day, steps * 12)


def visible_range(day: date, mode: str, first_weekday: int) -> tuple[date, date]:
    """The first and last day a view in the given mode needs data for."""
    if mode == WEEK:
        days = week_days(day, first_weekday)
        return days[0], days[-1]
    if mode == MONTH:
        grid = month_grid(day.year, day.month, first_weekday)
        return grid[0][0], grid[-1][-1]
    return date(day.year, 1, 1), date(day.year, 12, 31)


def assign_lanes(segments: list[tuple]) -> list[tuple]:
    """Place (item, start, end) segments side by side so overlapping ones never share a lane.

    Returns (item, start, end, lane, lanes) where lanes is the width, in lanes, of the
    cluster of mutually overlapping segments the item belongs to.
    """
    clusters = []
    current, lane_ends, cluster_end = [], [], 0
    for item, start, end in sorted(segments, key=lambda segment: (segment[1], -segment[2])):
        if current and start >= cluster_end:
            clusters.append((current, len(lane_ends)))
            current, lane_ends, cluster_end = [], [], 0
        lane = next((index for index, last in enumerate(lane_ends) if last <= start), len(lane_ends))
        if lane == len(lane_ends):
            lane_ends.append(end)
        else:
            lane_ends[lane] = end
        current.append((item, start, end, lane))
        cluster_end = max(cluster_end, end)
    if current:
        clusters.append((current, len(lane_ends)))
    return [(item, start, end, lane, lanes) for items, lanes in clusters
            for item, start, end, lane in items]
