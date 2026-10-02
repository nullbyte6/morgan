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
"""The overlay for creating, editing and deleting reminders and events."""
import re
from datetime import date, datetime, time, timedelta

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from src.init.lang import tr
from src.init.settings import ToggleSwitch

from . import formatting
from .calendar_paint import MiniMonth
from .entries import RECURRENCES, Entry, Reminder
from .store import NovaStore

REMINDER, EVENT = "reminder", "event"
TIME_INPUT = re.compile(r"(\d{1,2}):(\d{2})")
CARD_WIDTH = 480


def parse_time(text: str) -> time | None:
    match = TIME_INPUT.fullmatch(text.strip())
    if match is None:
        return None
    try:
        return time(int(match[1]), int(match[2]))
    except ValueError:
        return None


def next_full_hour(now: datetime | None = None) -> datetime:
    now = now or datetime.now()
    return now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)


class DateButton(QPushButton):
    """Shows a date and asks its dialog to open the month picker when pressed."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("novaDateButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._day = date.today()
        self.set_day(self._day)

    @property
    def day(self) -> date:
        return self._day

    def set_day(self, day: date) -> None:
        self._day = day
        self.setText(formatting.format_day(day, "nova.format.date"))


def _field(label: QLabel, content: QWidget) -> QWidget:
    field = QWidget()
    column = QVBoxLayout(field)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(6)
    column.addWidget(label)
    column.addWidget(content)
    return field


def _moment_row(day: DateButton, clock: QLineEdit) -> QWidget:
    row = QWidget()
    line = QHBoxLayout(row)
    line.setContentsMargins(0, 0, 0, 0)
    line.setSpacing(8)
    line.addWidget(day, 1)
    line.addWidget(clock)
    return row


class NovaEntryDialog(QWidget):
    """A scrim over the whole view with a card; Escape or a click outside the card closes it."""

    def __init__(self, store: NovaStore, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("novaScrim")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self._store = store
        self._kind = REMINDER
        self._editing: Entry | None = None
        self._previous_focus: QWidget | None = None
        self._pick_target = None
        parent.installEventFilter(self)

        self.title_label = QLabel()
        self.title_label.setObjectName("novaDialogTitle")
        self.segments = QButtonGroup(self)
        self.segments.setExclusive(True)
        self._kind_buttons: dict[str, QPushButton] = {}
        segments = QHBoxLayout()
        segments.setSpacing(6)
        for kind in (REMINDER, EVENT):
            button = QPushButton()
            button.setObjectName("novaSegment")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.toggled.connect(lambda checked, kind=kind: checked and self._select(kind))
            self.segments.addButton(button)
            self._kind_buttons[kind] = button
            segments.addWidget(button)
        segments.addStretch(1)
        self.segment_bar = QWidget()
        self.segment_bar.setLayout(segments)
        segments.setContentsMargins(0, 0, 0, 0)

        self.title_input = QLineEdit()
        self.title_input.setObjectName("novaInput")
        self.notes_input = QPlainTextEdit()
        self.notes_input.setObjectName("novaInput")
        self.notes_input.setFixedHeight(76)
        self.notes_input.setTabChangesFocus(True)
        self.start_day, self.end_day = DateButton(), DateButton()
        self.start_time, self.end_time = self._time_input(), self._time_input()
        self.all_day = ToggleSwitch()
        self.all_day_label = QLabel()
        self.all_day_label.setObjectName("novaFieldLabel")
        self.all_day_label.setBuddy(self.all_day)

        self.repeat = QButtonGroup(self)
        self.repeat.setExclusive(True)
        self._repeat_buttons: dict[str, QPushButton] = {}
        repeat_line = QHBoxLayout()
        repeat_line.setContentsMargins(0, 0, 0, 0)
        repeat_line.setSpacing(6)
        for recurrence in RECURRENCES:
            button = QPushButton()
            button.setObjectName("novaSegment")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.repeat.addButton(button)
            self._repeat_buttons[recurrence] = button
            repeat_line.addWidget(button)
        repeat_line.addStretch(1)
        repeat_bar = QWidget()
        repeat_bar.setLayout(repeat_line)

        self.labels = {name: self._label() for name in ("title", "notes", "start", "end", "repeat")}
        all_day_row = QWidget()
        toggle_line = QHBoxLayout(all_day_row)
        toggle_line.setContentsMargins(0, 0, 0, 0)
        toggle_line.addWidget(self.all_day_label)
        toggle_line.addStretch(1)
        toggle_line.addWidget(self.all_day)
        self.all_day_row = all_day_row
        self.start_field = _field(self.labels["start"], _moment_row(self.start_day, self.start_time))
        self.end_field = _field(self.labels["end"], _moment_row(self.end_day, self.end_time))
        self.repeat_field = _field(self.labels["repeat"], repeat_bar)

        self.error = QLabel()
        self.error.setObjectName("novaError")
        self.error.setWordWrap(True)
        self.error.hide()
        self.delete_button = self._button("novaDangerButton")
        self.cancel_button = self._button("novaSecondaryButton")
        self.save_button = self._button("novaPrimaryButton")
        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addWidget(self.delete_button)
        actions.addStretch(1)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.save_button)

        self.card = QFrame()
        self.card.setObjectName("novaCard")
        self.card.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation)
        self.card.installEventFilter(self)
        card = QVBoxLayout(self.card)
        card.setContentsMargins(24, 22, 24, 22)
        card.setSpacing(14)
        card.addWidget(self.title_label)
        card.addWidget(self.segment_bar)
        card.addWidget(_field(self.labels["title"], self.title_input))
        card.addWidget(_field(self.labels["notes"], self.notes_input))
        card.addWidget(self.all_day_row)
        card.addWidget(self.start_field)
        card.addWidget(self.end_field)
        card.addWidget(self.repeat_field)
        card.addWidget(self.error)
        card.addLayout(actions)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(self.card, 0, Qt.AlignmentFlag.AlignCenter)

        self.picker_frame = QFrame(self)
        self.picker_frame.setObjectName("novaPicker")
        self.picker_frame.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation)
        self.picker = MiniMonth()
        picker_layout = QHBoxLayout(self.picker_frame)
        picker_layout.setContentsMargins(6, 6, 6, 6)
        picker_layout.addWidget(self.picker)
        self.picker_frame.adjustSize()
        self.picker_frame.hide()

        self.start_day.clicked.connect(lambda: self._show_picker(self.start_day))
        self.end_day.clicked.connect(lambda: self._show_picker(self.end_day))
        self.picker.day_selected.connect(self._picked)
        self.all_day.toggled.connect(self._update_fields)
        self.title_input.returnPressed.connect(self._submit)
        self.title_input.textChanged.connect(self._update_save)
        self.save_button.clicked.connect(self._submit)
        self.cancel_button.clicked.connect(self.dismiss)
        self.delete_button.clicked.connect(self._delete)
        self.refresh_language()
        self.hide()

    @staticmethod
    def _label() -> QLabel:
        label = QLabel()
        label.setObjectName("novaFieldLabel")
        return label

    @staticmethod
    def _time_input() -> QLineEdit:
        field = QLineEdit()
        field.setObjectName("novaInput")
        field.setPlaceholderText("HH:mm")
        field.setFixedWidth(84)
        field.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return field

    @staticmethod
    def _button(name: str) -> QPushButton:
        button = QPushButton()
        button.setObjectName(name)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def refresh_language(self) -> None:
        for kind, button in self._kind_buttons.items():
            button.setText(tr(f"nova.{kind}"))
        self.labels["title"].setText(tr("nova.dialog.title"))
        self.labels["notes"].setText(tr("nova.dialog.notes"))
        self.title_input.setPlaceholderText(tr("nova.dialog.title_placeholder"))
        self.notes_input.setPlaceholderText(tr("nova.dialog.notes_placeholder"))
        self.all_day_label.setText(tr("nova.dialog.all_day"))
        self.labels["end"].setText(tr("nova.dialog.ends"))
        self.labels["repeat"].setText(tr("nova.dialog.repeat"))
        for recurrence, button in self._repeat_buttons.items():
            button.setText(tr(f"nova.repeat.{recurrence}"))
        self.cancel_button.setText(tr("nova.dialog.cancel"))
        self.save_button.setText(tr("nova.dialog.save"))
        self.delete_button.setText(tr("nova.dialog.delete"))
        self._retitle()
        for button in (self.start_day, self.end_day):
            button.set_day(button.day)

    def _retitle(self) -> None:
        action = "edit" if self._editing is not None else "new"
        self.title_label.setText(tr(f"nova.dialog.{action}_{self._kind}"))
        self.labels["start"].setText(tr("nova.dialog.remind_at" if self._kind == REMINDER
                                        else "nova.dialog.starts"))

    def open_new(self, kind: str = REMINDER, moment: datetime | None = None) -> None:
        self._editing = None
        self._begin()
        moment = moment or next_full_hour()
        self._fill(moment, moment + timedelta(hours=1), False)
        self._repeat_buttons["none"].setChecked(True)
        self.title_input.clear()
        self.notes_input.clear()
        self.segment_bar.show()
        self.delete_button.hide()
        self._kind_buttons[kind].setChecked(True)
        self._select(kind)
        self._reveal()

    def open_edit(self, entry: Entry) -> None:
        if not isinstance(entry, Reminder):
            entry = self._store.find_event(entry.id) or entry
        self._editing = entry
        self._begin()
        self._repeat_buttons[entry.recurrence].setChecked(True)
        if isinstance(entry, Reminder):
            self._fill(entry.remind_at, entry.remind_at + timedelta(hours=1), False)
            kind = REMINDER
        else:
            self._fill(entry.starts_at, entry.ends_at, entry.all_day)
            kind = EVENT
        self.title_input.setText(entry.title)
        self.notes_input.setPlainText(entry.notes)
        self.segment_bar.hide()
        self.delete_button.show()
        self._select(kind)
        self._reveal()

    def _begin(self) -> None:
        self._previous_focus = QApplication.focusWidget()
        self._set_error("")
        self.picker_frame.hide()

    def _fill(self, start: datetime, end: datetime, all_day: bool) -> None:
        self.start_day.set_day(start.date())
        self.end_day.set_day(end.date())
        self.start_time.setText(f"{start:%H:%M}")
        self.end_time.setText(f"{end:%H:%M}")
        self.all_day.setChecked(all_day)
        self.all_day.set_offset(1.0 if all_day else 0.0)

    def _reveal(self) -> None:
        self.setGeometry(self.parentWidget().rect())
        self._update_save()
        self.show()
        self.raise_()
        self.title_input.setFocus()

    def dismiss(self) -> None:
        self.picker_frame.hide()
        self.hide()
        if self._previous_focus is not None:
            try:
                self._previous_focus.setFocus()
            except RuntimeError:
                pass
        self._previous_focus = None

    def _select(self, kind: str) -> None:
        self._kind = kind
        self._set_error("")
        self._retitle()
        self._update_fields()

    def _update_fields(self) -> None:
        event = self._kind == EVENT
        timed = not (event and self.all_day.isChecked())
        self.all_day_row.setVisible(event)
        self.end_field.setVisible(event)
        self.start_time.setVisible(timed)
        self.end_time.setVisible(timed)

    def _update_save(self) -> None:
        self.save_button.setEnabled(bool(self.title_input.text().strip()))

    def _set_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.setVisible(bool(message))

    def _show_picker(self, button: DateButton) -> None:
        if self.picker_frame.isVisible() and self._pick_target is button:
            self.picker_frame.hide()
            return
        self._pick_target = button
        self.picker.set_selected(button.day)
        self.picker_frame.adjustSize()
        anchor = button.mapTo(self, QPoint(0, button.height() + 6))
        x = max(8, min(anchor.x(), self.width() - self.picker_frame.width() - 8))
        y = max(8, min(anchor.y(), self.height() - self.picker_frame.height() - 8))
        self.picker_frame.move(x, y)
        self.picker_frame.show()
        self.picker_frame.raise_()

    def _picked(self, day: date) -> None:
        target = self._pick_target
        self.picker_frame.hide()
        if target is None:
            return
        target.set_day(day)
        if self.start_day.day > self.end_day.day:
            self.end_day.set_day(self.start_day.day)

    def _moment(self, day: DateButton, clock: QLineEdit) -> datetime | None:
        if self._kind == EVENT and self.all_day.isChecked():
            return datetime.combine(day.day, time.min)
        value = parse_time(clock.text())
        if value is None:
            self._set_error(tr("nova.error.time"))
            return None
        return datetime.combine(day.day, value)

    def _submit(self) -> None:
        title = self.title_input.text().strip()
        if not title:
            return
        self._set_error("")
        notes = self.notes_input.toPlainText()
        start = self._moment(self.start_day, self.start_time)
        if start is None:
            return
        recurrence = next((name for name, button in self._repeat_buttons.items() if button.isChecked()), "none")
        try:
            if self._kind == REMINDER:
                if self._editing is None:
                    self._store.add_reminder(title, start, notes, recurrence)
                else:
                    self._store.update_reminder(self._editing.id, title, start, notes, recurrence)
            else:
                end = self._moment(self.end_day, self.end_time)
                if end is None:
                    return
                if end < start:
                    self._set_error(tr("nova.error.order"))
                    return
                all_day = self.all_day.isChecked()
                if self._editing is None:
                    self._store.add_event(title, start, end, all_day=all_day, notes=notes, recurrence=recurrence)
                else:
                    self._store.update_event(self._editing.id, title, start, end, all_day=all_day, notes=notes,
                                             recurrence=recurrence)
        except (ValueError, OSError) as error:
            self._set_error(str(error))
            return
        self.dismiss()

    def _delete(self) -> None:
        entry = self._editing
        if entry is None:
            return
        try:
            if isinstance(entry, Reminder):
                self._store.delete_reminder(entry.id)
            else:
                self._store.delete_event(entry.id)
        except OSError as error:
            self._set_error(str(error))
            return
        self.dismiss()

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize and self.isVisible():
            self.setGeometry(self.parentWidget().rect())
        elif (watched is self.card and event.type() == QEvent.Type.MouseButtonPress
                and self.picker_frame.isVisible()):
            self.picker_frame.hide()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.card.setFixedWidth(max(280, min(CARD_WIDTH, self.width() - 32)))

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            if self.picker_frame.isVisible():
                self.picker_frame.hide()
            else:
                self.dismiss()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        if self.picker_frame.isVisible():
            self.picker_frame.hide()
        else:
            self.dismiss()

    def focusNextPrevChild(self, forward: bool) -> bool:
        stops = [widget for widget in self.card.findChildren(QWidget)
                 if widget.isVisible() and widget.isEnabled()
                 and widget.focusPolicy() & Qt.FocusPolicy.TabFocus]
        if not stops:
            return super().focusNextPrevChild(forward)
        current = QApplication.focusWidget()
        while current is not None and current not in stops:
            current = current.parentWidget()
        if current is None:
            target = stops[0] if forward else stops[-1]
        else:
            target = stops[(stops.index(current) + (1 if forward else -1)) % len(stops)]
        target.setFocus(Qt.FocusReason.TabFocusReason if forward else Qt.FocusReason.BacktabFocusReason)
        return True
