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
"""The areas of Nova: four hubs in the sidebar, each opening a grid of sections."""
from enum import Enum

from src.init.lang import tr


class Section(Enum):
    AGENDA = ("agenda", "\U000f00f5")
    REMINDERS = ("reminders", "\U000f009a")
    EVENTS = ("events", "\U000f09d2")
    CALENDAR = ("calendar", "\U000f0e17")
    DIARY = ("diary", "\U000f0bc2")
    JOURNAL = ("journal", "\U000f082e")
    REVIEW = ("review", "\U000f0a33")
    MEMORIES = ("memories", "\U000f09d1")
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

    @property
    def hub(self) -> "Hub":
        return next(hub for hub in Hub if self in hub.sections)


class Hub(Enum):
    HOME = ("home", "\U000f02dc")
    NOTIFICATIONS = ("notifications", "\U000f009a")
    ME = ("me", "\U000f0004")
    SEARCH = ("search", "\U000f0349")

    def __init__(self, key: str, glyph: str):
        self.key = key
        self.glyph = glyph

    @property
    def title(self) -> str:
        return tr(f"nova.hub.{self.key}")

    @property
    def tagline(self) -> str:
        return tr(f"nova.hub.{self.key}.tagline")

    @property
    def sections(self) -> tuple[Section, ...]:
        return HUB_SECTIONS[self]

    @property
    def is_grid(self) -> bool:
        return self is not Hub.SEARCH


HUB_SECTIONS = {
    Hub.HOME: (Section.AGENDA, Section.EVENTS, Section.CALENDAR, Section.REVIEW),
    Hub.NOTIFICATIONS: (Section.REMINDERS,),
    Hub.ME: (Section.DIARY, Section.JOURNAL, Section.MEMORIES),
    Hub.SEARCH: (Section.SEARCH,),
}
