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
"""Persistent reminders and events with change notification for the interface."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .records import NovaRecords


class NovaStore(QObject, NovaRecords):
    """Nova's records for the desktop, announcing every change through a Qt signal."""

    changed = Signal()

    def __init__(self, directory: Path | str | None = None, parent: QObject | None = None):
        QObject.__init__(self, parent)
        self.open(directory)

    def _changed(self) -> None:
        self.changed.emit()
