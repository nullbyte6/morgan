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
"""A shared desktop projection of TaskControl and observable transport events."""

from PySide6.QtCore import QObject, Signal, Slot

from src.init.task_view import TaskProjection, TaskView

__all__ = ["TaskPresentation", "TaskView"]


class TaskPresentation(TaskProjection, QObject):
    changed = Signal(object)

    def __init__(self, parent=None):
        QObject.__init__(self, parent)
        TaskProjection.__init__(self)

    @Slot(int, object)
    def on_activity(self, turn_id, activity):
        super().on_activity(turn_id, activity)

    @Slot(int, str)
    def on_phase(self, turn_id, phase):
        super().on_phase(turn_id, phase)

    @Slot(int, str)
    def set_task_title(self, turn_id, title):
        super().set_task_title(turn_id, title)
