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
"""The journal: the user's own entries for each day, written here or dictated to the assistant."""
from datetime import date, timedelta

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from src.init.lang import tr

from . import formatting
from .calendar_paint import CHEVRON_LEFT, CHEVRON_RIGHT
from .entries import JournalEntry
from .journal import local_moment
from .memories import EDIT, _icon_button, _text_button
from .messages import RemoveButton, code_font_family
from .store import NovaStore

REMOVE_TOOLTIPS = ("nova.journal.remove", "nova.journal.remove_confirm")


def _label(text: str, name: str, wrap: bool = True) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


class JournalCard(QFrame):
    """One journal entry with who wrote it and when, and buttons to edit its text in place or delete it."""

    edit_requested = Signal(str, str)
    remove_requested = Signal(str)

    def __init__(self, entry: JournalEntry, parent: QWidget | None = None):
        super().__init__(parent)
        self.entry = entry
        self.setObjectName("novaRow")
        family = code_font_family()

        self.content = _label(entry.text, "novaRowTitle")
        self.content.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        author = tr("nova.journal.by_user" if entry.author == "user" else "nova.journal.by_assistant")
        details = [author, formatting.time_text(local_moment(entry.created_at))]
        if entry.is_edited:
            details.append(tr("nova.journal.edited"))
        self.caption = _label(" · ".join(details), "novaRowCaption")

        self.editor = QPlainTextEdit(entry.text)
        self.editor.setObjectName("novaInput")
        self.editor.setFixedHeight(140)
        self.editor.setTabChangesFocus(True)
        self.editor.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.error = _label("", "novaError")
        self.error.hide()
        self.save_button = _text_button("novaPrimaryButton")
        self.save_button.setText(tr("nova.dialog.save"))
        self.cancel_button = _text_button("novaSecondaryButton")
        self.cancel_button.setText(tr("nova.dialog.cancel"))
        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addStretch(1)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.save_button)
        self.edit_area = QWidget()
        edit_column = QVBoxLayout(self.edit_area)
        edit_column.setContentsMargins(0, 6, 0, 0)
        edit_column.setSpacing(8)
        edit_column.addWidget(self.editor)
        edit_column.addWidget(self.error)
        edit_column.addLayout(actions)
        self.edit_area.hide()

        self.edit_button = _icon_button(EDIT, family)
        self.edit_button.setToolTip(tr("nova.journal.edit"))
        self.remove_button = RemoveButton(family, tooltips=REMOVE_TOOLTIPS)

        details_column = QVBoxLayout()
        details_column.setSpacing(3)
        details_column.addWidget(self.content)
        details_column.addWidget(self.caption)
        details_column.addWidget(self.edit_area)
        buttons = QHBoxLayout()
        buttons.setSpacing(4)
        for button in (self.edit_button, self.remove_button):
            buttons.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 13, 16, 13)
        row.setSpacing(14)
        row.addLayout(details_column, 1)
        row.addLayout(buttons)
        
        self.edit_button.clicked.connect(lambda: self.set_editing(True))
        self.cancel_button.clicked.connect(lambda: self.set_editing(False))
        self.save_button.clicked.connect(self._save)
        self.remove_button.confirmed.connect(lambda: self.remove_requested.emit(entry.id))

    @property
    def editing(self) -> bool:
        return not self.edit_area.isHidden()

    def set_editing(self, editing: bool) -> None:
        if not editing:
            self.editor.setPlainText(self.entry.text)
            self.show_error("")
        self.content.setVisible(not editing)
        self.edit_area.setVisible(editing)
        if editing:
            self.editor.setFocus()

    def show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.setVisible(bool(message))

    def _save(self) -> None:
        text = self.editor.toPlainText().strip()
        if text and text != self.entry.text:
            self.edit_requested.emit(self.entry.id, text)
        else:
            self.set_editing(False)


class JournalView(QWidget):
    """One day of the user's journal: a box to write a new entry and the entries already written."""

    def __init__(self, store: NovaStore, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("novaJournal")
        self._store = store
        self._day = date.today()
        self._signature = None

        self.previous = self._arrow(CHEVRON_LEFT)
        self.next = self._arrow(CHEVRON_RIGHT)
        self.day_label = QLabel()
        self.day_label.setObjectName("novaDiaryDay")
        self.day_label.setMinimumWidth(0)
        self.day_label.setWordWrap(True)
        self.earlier_button = QPushButton()
        self.earlier_button.setObjectName("novaTodayButton")
        self.earlier_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.today_button = QPushButton()
        self.today_button.setObjectName("novaTodayButton")
        self.today_button.setCursor(Qt.CursorShape.PointingHandCursor)
        header = QHBoxLayout()
        header.setSpacing(6)
        header.addWidget(self.previous)
        header.addWidget(self.next)
        header.addSpacing(8)
        header.addWidget(self.day_label, 1)
        actions = QHBoxLayout()
        actions.setSpacing(6)
        actions.addWidget(self.earlier_button)
        actions.addWidget(self.today_button)
        actions.addStretch(1)
        top = QVBoxLayout()
        top.setSpacing(8)
        top.addLayout(header)
        top.addLayout(actions)

        self.composer = QPlainTextEdit()
        self.composer.setObjectName("novaInput")
        self.composer.setFixedHeight(104)
        self.composer.setTabChangesFocus(True)
        self.composer_error = _label("", "novaError")
        self.composer_error.hide()
        self.add_button = _text_button("novaPrimaryButton")
        self.add_button.setEnabled(False)
        compose_actions = QHBoxLayout()
        compose_actions.addWidget(self.composer_error, 1)
        compose_actions.addWidget(self.add_button, 0, Qt.AlignmentFlag.AlignRight)
        compose = QVBoxLayout()
        compose.setSpacing(8)
        compose.addWidget(self.composer)
        compose.addLayout(compose_actions)

        self._rows = QVBoxLayout()
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(8)
        self._rows.addStretch(1)
        body = QWidget()
        body.setObjectName("novaEntryBody")
        body.setLayout(self._rows)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("novaScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.setWidget(body)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addLayout(top)
        layout.addLayout(compose)
        layout.addWidget(self.scroll, 1)

        self.previous.clicked.connect(lambda: self.set_day(self._day - timedelta(days=1)))
        self.next.clicked.connect(lambda: self.set_day(self._day + timedelta(days=1)))
        self.today_button.clicked.connect(lambda: self.set_day(date.today()))
        self.earlier_button.clicked.connect(self._jump_earlier)
        self.composer.textChanged.connect(self._composer_changed)
        self.add_button.clicked.connect(self._add_entry)
        send = QShortcut(QKeySequence("Ctrl+Return"), self.composer)
        send.setContext(Qt.ShortcutContext.WidgetShortcut)
        send.activated.connect(self._add_entry)
        store.changed.connect(self._store_changed)
        self.refresh_language()

    @staticmethod
    def _arrow(glyph: str) -> QPushButton:
        button = QPushButton(glyph)
        button.setObjectName("novaArrow")
        button.setFixedSize(34, 34)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    @property
    def day(self) -> date:
        return self._day

    def set_day(self, day: date) -> None:
        self._day = day
        self.refresh()

    def refresh_language(self) -> None:
        self.previous.setToolTip(tr("nova.calendar.previous"))
        self.next.setToolTip(tr("nova.calendar.next"))
        self.earlier_button.setText(tr("nova.diary.previous_entry"))
        self.today_button.setText(tr("nova.calendar.today"))
        self.composer.setPlaceholderText(tr("nova.journal.placeholder"))
        self.add_button.setText(tr("nova.journal.save"))
        self.refresh()

    def _store_changed(self) -> None:
        if self.isVisible():
            self.refresh(force=False)

    def _composer_changed(self) -> None:
        self.add_button.setEnabled(bool(self.composer.toPlainText().strip()))
        self.composer_error.hide()

    def _jump_earlier(self) -> None:
        try:
            day = self._store.adjacent_journal_day(self._day, earlier=True)
        except Exception:
            return
        if day is not None:
            self.set_day(day)

    def _add_entry(self) -> None:
        text = self.composer.toPlainText().strip()
        if not text:
            return
        try:
            self._store.add_journal_entry(text, self._day, "user")
        except Exception as error:
            self.composer_error.setText(str(error))
            self.composer_error.show()
            return
        self.composer.clear()
        scrollbar = self.scroll.verticalScrollBar()
        QTimer.singleShot(0, lambda: scrollbar.setValue(scrollbar.maximum()))

    def _edit(self, card: JournalCard, entry_id: str, text: str) -> None:
        try:
            self._store.update_journal_entry(entry_id, text)
        except Exception as error:
            card.show_error(str(error))
            return
        self.refresh()

    def _remove(self, entry_id: str) -> None:
        try:
            self._store.delete_journal_entry(entry_id)
        except Exception as error:
            self._add(_label(tr("nova.journal.error", error=error), "novaDiaryNote"))
            return
        self.refresh()

    def _add(self, widget: QWidget) -> None:
        self._rows.insertWidget(self._rows.count() - 1, widget)

    def refresh(self, force: bool = True) -> None:
        """Rebuild the entries of the day, unless nothing changed and force is off or one is being edited."""
        error = None
        entries: list[JournalEntry] = []
        try:
            entries = self._store.journal_entries(self._day, self._day)
            earlier = self._store.adjacent_journal_day(self._day, earlier=True)
        except Exception as failure:
            error, earlier = str(failure), None
        self.day_label.setText(formatting.day_heading(self._day))
        self.earlier_button.setEnabled(earlier is not None)
        signature = (self._day, error, tuple((entry.id, entry.modified_at) for entry in entries))
        if not force and (signature == self._signature or any(
                card.editing for card in self.findChildren(JournalCard))):
            return
        same_day = self._signature is not None and self._signature[0] == self._day
        self._signature = signature
        scrollbar = self.scroll.verticalScrollBar()
        position = scrollbar.value() if same_day else 0
        while self._rows.count() > 1:
            widget = self._rows.takeAt(0).widget()
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        for entry in entries:
            card = JournalCard(entry)
            card.edit_requested.connect(lambda entry_id, text, card=card: self._edit(card, entry_id, text))
            card.remove_requested.connect(self._remove)
            self._add(card)
        if error is not None:
            self._add(_label(tr("nova.journal.error", error=error), "novaDiaryNote"))
        elif not entries:
            self._add(_label(tr("nova.journal.empty"), "novaDiaryNote"))
        QTimer.singleShot(0, lambda: scrollbar.setValue(position))

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
