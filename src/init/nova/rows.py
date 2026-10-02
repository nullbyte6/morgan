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
"""Entry rows and the scrolling, grouped list that shows them."""
from datetime import datetime

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QStackedLayout, QVBoxLayout, QWidget)

from src.init.lang import tr
from src.init.theme import on_theme_changed

from . import formatting
from .calendar_paint import ALIGN_CENTER, color, draw_text, glyph_font
from .entries import Entry, Reminder, recurrence_label

CHECK = "\U000f012c"
STAR = "\U000f0ae2"
EVENT_GLYPH = "\U000f09d2"
REPEAT = "\u21bb"
PENCIL = "\U000f03eb"
FLAG = "\U000f023b"


class CircleCheck(QAbstractButton):
    """A round check box that fills with the accent color when checked."""

    SIZE = 24

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("novaCheck")
        self.setCheckable(True)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        on_theme_changed(self._theme_changed)

    def _theme_changed(self, _theme) -> None:
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(self.SIZE, self.SIZE)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        disc = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        if self.isChecked():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color("accent"))
            painter.drawEllipse(disc)
            draw_text(painter, self.rect(), CHECK, glyph_font(14), "on_accent", ALIGN_CENTER)
        else:
            painter.setPen(QPen(color("accent" if self.underMouse() else "border_strong"), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(disc)
        painter.end()


def caption(entry: Entry) -> str:
    repeat = f" · {REPEAT} {recurrence_label(entry.recurrence, tr)}" if entry.is_recurring else ""
    if isinstance(entry, Reminder):
        return f"{tr('nova.reminder')} · {formatting.date_time_text(entry.remind_at)}{repeat}"
    span = formatting.event_time_text(entry)
    if entry.starts_at.date() == entry.ends_at.date() or (entry.all_day and entry.first_day == entry.last_day):
        return (f"{tr('nova.event')} · {formatting.format_day(entry.first_day, 'nova.format.short_day')}"
                f" · {span}{repeat}")
    return f"{tr('nova.event')} · {span}{repeat}"


class EntryRow(QFrame):
    """One reminder or event: a check box or marker, its title, notes and when it happens."""

    activated = Signal(object)
    toggled = Signal(object, bool)

    def __init__(self, entry: Entry, now: datetime, parent: QWidget | None = None):
        super().__init__(parent)
        self.entry = entry
        self.setObjectName("novaRow")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        completed = isinstance(entry, Reminder) and entry.is_completed
        overdue = isinstance(entry, Reminder) and not entry.is_completed and entry.remind_at < now
        self.setProperty("completed", completed)
        self.setProperty("overdue", overdue)

        title = QLabel(entry.title)
        title.setObjectName("novaRowTitle")
        title.setWordWrap(True)
        font = title.font()
        font.setStrikeOut(completed)
        title.setFont(font)
        details = QVBoxLayout()
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(3)
        details.addWidget(title)
        if entry.notes:
            notes = QLabel(entry.notes)
            notes.setObjectName("novaRowNotes")
            notes.setWordWrap(True)
            details.addWidget(notes)
        when = QLabel(caption(entry))
        when.setObjectName("novaRowCaption")
        details.addWidget(when)

        if isinstance(entry, Reminder):
            marker = CircleCheck()
            marker.setChecked(entry.is_completed)
            marker.toggled.connect(lambda done: self.toggled.emit(self.entry, done))
        else:
            marker = QLabel(EVENT_GLYPH)
            marker.setObjectName("novaRowMarker")
            marker.setFixedSize(CircleCheck.SIZE, CircleCheck.SIZE)
            marker.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 13, 16, 13)
        row.setSpacing(14)
        row.addWidget(marker, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(details, 1)

        edit = QPushButton(PENCIL)
        edit.setObjectName("novaRowEdit")
        edit.setFixedSize(30, 30)
        edit.setCursor(Qt.CursorShape.PointingHandCursor)
        edit.setToolTip(tr("nova.row.edit"))
        edit.setAccessibleName(tr("nova.row.edit"))
        edit.clicked.connect(lambda: self.activated.emit(self.entry))
        if entry.flag != "none":
            flag = QLabel(FLAG)
            flag.setObjectName("novaRowFlag")
            flag.setProperty("flag", entry.flag)
            flag.setFixedSize(CircleCheck.SIZE, 30)
            flag.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addWidget(flag, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(edit, 0, Qt.AlignmentFlag.AlignTop)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.activated.emit(self.entry)
        super().mouseReleaseEvent(event)


class EntryList(QWidget):
    """Groups of entry rows under small headings, or a friendly placeholder when empty."""

    activated = Signal(object)
    toggled = Signal(object, bool)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("novaEntryList")
        self._rows = QVBoxLayout()
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(8)
        self._rows.addStretch(1)
        body = QWidget()
        body.setObjectName("novaEntryBody")
        body.setLayout(self._rows)
        self._scroll = QScrollArea()
        self._scroll.setObjectName("novaScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.viewport().setAutoFillBackground(False)
        self._scroll.setWidget(body)

        self._mark = QLabel(STAR)
        self._mark.setObjectName("novaWelcomeMark")
        self._title = QLabel(tr("nova.empty.title"))
        self._title.setObjectName("novaWelcomeTitle")
        self._text = QLabel()
        self._text.setObjectName("novaWelcomeText")
        self._text.setWordWrap(True)
        self._text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome = QWidget()
        welcome.setObjectName("novaWelcome")
        column = QVBoxLayout(welcome)
        column.setSpacing(10)
        column.addStretch(1)
        for widget in (self._mark, self._title, self._text):
            column.addWidget(widget, 0, Qt.AlignmentFlag.AlignHCenter)
        column.addStretch(1)

        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._stack.addWidget(welcome)
        self._stack.addWidget(self._scroll)

    def set_groups(self, groups: list[tuple[str, list[Entry]]], empty_text: str) -> None:
        scrollbar = self._scroll.verticalScrollBar()
        position = scrollbar.value()
        while self._rows.count() > 1:
            widget = self._rows.takeAt(0).widget()
            widget.setParent(None)
            widget.deleteLater()
        now = datetime.now()
        index = 0
        for heading, entries in groups:
            if not entries:
                continue
            label = QLabel(heading)
            label.setObjectName("novaGroup")
            self._rows.insertWidget(index, label)
            index += 1
            for entry in entries:
                row = EntryRow(entry, now)
                row.activated.connect(self.activated)
                row.toggled.connect(self.toggled)
                self._rows.insertWidget(index, row)
                index += 1
        self._text.setText(empty_text)
        self._title.setText(tr("nova.empty.title"))
        self._stack.setCurrentIndex(1 if index else 0)
        QTimer.singleShot(0, lambda: scrollbar.setValue(position))
