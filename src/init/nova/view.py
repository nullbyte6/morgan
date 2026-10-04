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
"""Nova as a workspace view: a sidebar folded into the panel, with the agenda beside it."""
from datetime import datetime

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QStackedWidget,
                               QVBoxLayout, QWidget)

from src.init.lang import tr

from . import formatting
from .agenda import agenda_groups, event_groups, reminder_groups
from .calendar_view import CalendarView
from .dialog import EVENT, REMINDER, NovaEntryDialog
from .diary import DiaryView
from .entries import Entry, Reminder
from .hub_view import HubGrid
from .journal_view import JournalView
from .memories import MemoriesView
from .review import ReviewView
from .rows import EntryList
from .search import SearchView
from .sections import Hub, Section
from .sidebar import NovaSidebar
from .store import NovaStore

PLUS = "\U000f0415"
NARROW_WIDTH = 560
MINIMUM_FOR_LABELS = 420
REFRESH_MS = 30_000


class NovaView(QWidget):
    """Nova's four hubs and their sections inside one workspace panel."""

    def __init__(self, store: NovaStore, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("novaView")
        self.setProperty("workspaceEmpty", False)
        self._store = store
        self._hub = Hub.HOME
        self._section: Section | None = None
        self._user_collapsed: bool | None = None

        self.sidebar = NovaSidebar(self._hub)
        divider = QFrame()
        divider.setObjectName("novaDivider")
        divider.setFixedWidth(1)

        self.title = QLabel()
        self.title.setObjectName("novaTitle")
        self.tagline = QLabel()
        self.tagline.setObjectName("novaTagline")
        for label in (self.title, self.tagline):
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.back = QPushButton()
        self.back.setObjectName("novaBack")
        self.back.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        policy = self.back.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.back.setSizePolicy(policy)
        heading = QVBoxLayout()
        heading.setSpacing(3)
        heading.addWidget(self.back, 0, Qt.AlignmentFlag.AlignLeft)
        heading.addWidget(self.title)
        heading.addWidget(self.tagline)
        self.add_button = QPushButton(PLUS)
        self.add_button.setObjectName("novaAdd")
        self.add_button.setFixedSize(42, 42)
        self.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        top = QHBoxLayout()
        top.setSpacing(16)
        top.addLayout(heading, 1)
        top.addWidget(self.add_button, 0, Qt.AlignmentFlag.AlignTop)

        self.lists = {section: EntryList() for section in (Section.AGENDA, Section.REMINDERS, Section.EVENTS)}
        self.calendar = CalendarView(store)
        self.diary = DiaryView(store)
        self.journal = JournalView(store)
        self.search = SearchView(store)
        self.memories = MemoriesView()
        self.review = ReviewView(store)
        self.grids = {hub: HubGrid(hub) for hub in Hub if hub.is_grid}
        pages = {Section.CALENDAR: self.calendar, Section.DIARY: self.diary, Section.JOURNAL: self.journal,
                 Section.MEMORIES: self.memories, Section.SEARCH: self.search, Section.REVIEW: self.review}
        self.pages = QStackedWidget()
        for section in Section:
            self.pages.addWidget(pages.get(section) or self.lists[section])
        for grid in self.grids.values():
            self.pages.addWidget(grid)

        content = QVBoxLayout()
        content.setContentsMargins(28, 22, 28, 22)
        content.setSpacing(18)
        content.addLayout(top)
        content.addWidget(self.pages, 1)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.sidebar)
        layout.addWidget(divider)
        layout.addLayout(content, 1)

        self.dialog = NovaEntryDialog(store, self)

        self.sidebar.hub_selected.connect(self.show_hub)
        self.back.clicked.connect(lambda: self.show_hub(self._hub))
        for grid in self.grids.values():
            grid.section_selected.connect(self.show_section)
        self.sidebar.toggle_requested.connect(self._toggle_sidebar)
        self.add_button.clicked.connect(self._add)
        for entries in self.lists.values():
            entries.activated.connect(self.dialog.open_edit)
            entries.toggled.connect(self._toggle_reminder)
        self.calendar.entry_activated.connect(self.dialog.open_edit)
        self.diary.entry_activated.connect(self.dialog.open_edit)
        self.search.entry_activated.connect(self.dialog.open_edit)
        self.search.day_selected.connect(self._open_day)
        self.search.journal_selected.connect(self._open_journal_day)
        self.review.day_selected.connect(self._open_day)
        self.calendar.create_requested.connect(lambda moment: self.dialog.open_new(EVENT, moment))
        store.changed.connect(self._refresh)

        self.clock = QTimer(self)
        self.clock.setInterval(REFRESH_MS)
        self.clock.timeout.connect(self._refresh)
        self.show_hub(Hub.HOME)
        self.refresh_language()

    def minimumSizeHint(self) -> QSize:
        return QSize(360, 260)

    @property
    def hub(self) -> Hub:
        return self._hub

    @property
    def section(self) -> Section | None:
        return self._section

    def show_hub(self, hub: Hub) -> None:
        """Show the grid of a hub, or straight the search page for the search hub."""
        if hub is Hub.SEARCH:
            self.show_section(Section.SEARCH)
            return
        self._hub = hub
        self._section = None
        self.sidebar.select(hub)
        self.add_button.hide()
        self.back.hide()
        self.pages.setCurrentWidget(self.grids[hub])
        self._refresh()

    def show_section(self, section: Section) -> None:
        self._section = section
        self._hub = section.hub
        self.sidebar.select(self._hub)
        self.add_button.setVisible(section not in (Section.DIARY, Section.JOURNAL, Section.REVIEW,
                                                   Section.MEMORIES, Section.SEARCH))
        self.back.setVisible(self._hub.is_grid)
        self.pages.setCurrentIndex(list(Section).index(section))
        self._refresh()
        if section is Section.SEARCH:
            self.search.focus()

    def _open_day(self, day) -> None:
        self.diary.set_day(day)
        self.show_section(Section.DIARY)

    def _open_journal_day(self, day) -> None:
        self.journal.set_day(day)
        self.show_section(Section.JOURNAL)

    def refresh_language(self) -> None:
        self.sidebar.refresh_language()
        for grid in self.grids.values():
            grid.refresh_language()
        self.dialog.refresh_language()
        self.calendar.refresh_language()
        self.diary.refresh_language()
        self.journal.refresh_language()
        self.search.refresh_language()
        self.memories.refresh_language()
        self.review.refresh_language()
        self.add_button.setToolTip(tr("nova.add"))
        self._refresh()

    def _refresh(self) -> None:
        now = datetime.now()
        page = self._section or self._hub
        self.title.setText(page.title)
        self.tagline.setText(page.tagline)
        self.back.setText(f"‹  {self._hub.title}")
        self.lists[Section.AGENDA].set_groups(agenda_groups(self._store, now, formatting.day_heading), tr("nova.empty.agenda"))
        self.lists[Section.REMINDERS].set_groups(reminder_groups(self._store), tr("nova.empty.reminders"))
        self.lists[Section.EVENTS].set_groups(event_groups(self._store, now), tr("nova.empty.events"))

    def _add(self) -> None:
        kind = EVENT if self._section in (Section.EVENTS, Section.CALENDAR) else REMINDER
        moment = self.calendar.create_for(self.calendar.day) if self._section is Section.CALENDAR else None
        self.dialog.open_new(kind, moment)

    def _toggle_reminder(self, entry: Entry, done: bool) -> None:
        if isinstance(entry, Reminder):
            self._store.set_reminder_completed(entry.id, done)

    def _toggle_sidebar(self) -> None:
        self._user_collapsed = not self.sidebar.collapsed
        self._apply_sidebar()

    def _apply_sidebar(self) -> None:
        if self.width() < MINIMUM_FOR_LABELS:
            collapsed = True
        elif self._user_collapsed is not None:
            collapsed = self._user_collapsed
        else:
            collapsed = self.width() < NARROW_WIDTH
        self.sidebar.set_collapsed(collapsed)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_sidebar()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh()
        self.clock.start()

    def hideEvent(self, event):
        self.clock.stop()
        super().hideEvent(event)

    def dispose(self) -> None:
        self.clock.stop()
        self.calendar.clock.stop()
