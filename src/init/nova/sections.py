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
"""The areas of Nova, in sidebar order."""
from enum import Enum

from src.init.lang import tr


class Section(Enum):
    AGENDA = ("agenda", "\U000f00f5")
    REMINDERS = ("reminders", "\U000f009a")
    EVENTS = ("events", "\U000f09d2")
    CALENDAR = ("calendar", "\U000f0e17")
    DIARY = ("diary", "\U000f082e")
    SEARCH = ("search", "\U000f0349")

    def __init__(self, key: str, glyph: str):
        self.key = key
        self.glyph = glyph

    @property
    def title(self) -> str:
        return tr(f"nova.section.{self.key}")

    @property
    def tagline(self) -> str:
        return tr(f"nova.section.{self.key}.tagline")
