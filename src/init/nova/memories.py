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
"""What Arlo remembers: every stored fact, pinned ones first, to review, pin, edit or remove."""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from src.init.lang import tr
from src.init.memory.integration import configured_service

from . import formatting
from .diary import local_moment
from .messages import RemoveButton, code_font_family

PIN = "\U000f0403"
UNPIN = "\U000f0931"
EDIT = "\U000f03eb"


def _label(text: str, name: str, wrap: bool = True) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


def _icon_button(glyph: str, family: str) -> QPushButton:
    button = QPushButton(glyph)
    button.setObjectName("logCopyNav")
    font = button.font()
    font.setFamily(family)
    font.setPixelSize(16)
    button.setFont(font)
    button.setFixedSize(24, 24)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def _text_button(name: str) -> QPushButton:
    button = QPushButton()
    button.setObjectName(name)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


class MemoryRow(QFrame):
    """One stored memory with buttons to pin it, edit its text in place or remove it."""

    pin_requested = Signal(str, bool)
    edit_requested = Signal(str, str, str)
    remove_requested = Signal(str)

    def __init__(self, memory: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.memory = memory
        self.setObjectName("novaRow")
        pinned = bool(memory["pinned"])
        family = code_font_family()

        self.content = _label(memory["content"], "novaRowTitle")
        category = tr(f"nova.diary.category.{memory['category']}")
        when = formatting.date_time_text(local_moment(memory["modified_at"]))
        details = [category, when] + ([tr("nova.memories.pinned_mark")] if pinned else [])
        self.caption = _label(" · ".join(details), "novaRowCaption", wrap=False)

        self.editor = QPlainTextEdit(memory["content"])
        self.editor.setObjectName("novaInput")
        self.editor.setFixedHeight(84)
        self.editor.setTabChangesFocus(True)
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

        self.pin_button = _icon_button(PIN if pinned else UNPIN, family)
        self.pin_button.setProperty("pinned", pinned)
        self.pin_button.setToolTip(tr("nova.memories.unpin" if pinned else "nova.memories.pin"))
        self.edit_button = _icon_button(EDIT, family)
        self.edit_button.setToolTip(tr("nova.memories.edit"))
        self.remove_button = RemoveButton(family)

        details_column = QVBoxLayout()
        details_column.setSpacing(3)
        details_column.addWidget(self.content)
        details_column.addWidget(self.caption)
        details_column.addWidget(self.edit_area)
        buttons = QHBoxLayout()
        buttons.setSpacing(4)
        for button in (self.pin_button, self.edit_button, self.remove_button):
            buttons.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 13, 16, 13)
        row.setSpacing(14)
        row.addLayout(details_column, 1)
        row.addLayout(buttons)

        self.pin_button.clicked.connect(lambda: self.pin_requested.emit(memory["id"], not pinned))
        self.edit_button.clicked.connect(lambda: self.set_editing(True))
        self.cancel_button.clicked.connect(lambda: self.set_editing(False))
        self.save_button.clicked.connect(self._save)
        self.remove_button.confirmed.connect(lambda: self.remove_requested.emit(memory["id"]))

    def set_editing(self, editing: bool) -> None:
        if not editing:
            self.editor.setPlainText(self.memory["content"])
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
        if text and text != self.memory["content"]:
            self.edit_requested.emit(self.memory["id"], text, self.memory["category"])
        else:
            self.set_editing(False)


class MemoriesView(QWidget):
    """Every confirmed memory, pinned ones first; pinned memories are always part of the model's context."""

    def __init__(self, memory=configured_service, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("novaMemories")
        self._memory = memory

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
        layout.addWidget(self.scroll, 1)

    def refresh_language(self) -> None:
        if self.isVisible():
            self.refresh()

    def _service(self):
        try:
            return self._memory(), None
        except Exception as error:
            return None, str(error)

    def _add(self, widget: QWidget) -> None:
        self._rows.insertWidget(self._rows.count() - 1, widget)

    def refresh(self) -> None:
        scrollbar = self.scroll.verticalScrollBar()
        position = scrollbar.value()
        while self._rows.count() > 1:
            widget = self._rows.takeAt(0).widget()
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        service, error = self._service()
        memories = []
        if service is not None:
            try:
                memories = service.stored_memories()
            except Exception as failure:
                error = str(failure)
        groups = ((tr("nova.memories.pinned"), [memory for memory in memories if memory["pinned"]]),
                  (tr("nova.memories.stored"), [memory for memory in memories if not memory["pinned"]]))
        for heading, found in groups:
            if not found:
                continue
            self._add(_label(heading, "novaGroup"))
            for memory in found:
                row = MemoryRow(memory)
                row.pin_requested.connect(self._pin)
                row.edit_requested.connect(lambda memory_id, text, category, row=row:
                                           self._edit(row, memory_id, text, category))
                row.remove_requested.connect(self._remove)
                self._add(row)
        if error is not None:
            self._add(_label(tr("nova.diary.error", error=error), "novaDiaryNote"))
        elif service is None:
            self._add(_label(tr("nova.diary.disabled"), "novaDiaryNote"))
        elif not memories:
            self._add(_label(tr("nova.memories.empty"), "novaDiaryNote"))
        QTimer.singleShot(0, lambda: scrollbar.setValue(position))

    def _apply(self, action) -> str | None:
        service, error = self._service()
        if service is None:
            return error
        try:
            action(service)
        except Exception as failure:
            return str(failure)
        return None

    def _pin(self, memory_id: str, pinned: bool) -> None:
        self._apply(lambda service: service.pin_memory(memory_id, pinned))
        self.refresh()

    def _edit(self, row: MemoryRow, memory_id: str, text: str, category: str) -> None:
        error = self._apply(lambda service: service.update_memory(memory_id, text, category=category))
        if error is not None:
            row.show_error(error)
            return
        self.refresh()

    def _remove(self, memory_id: str) -> None:
        self._apply(lambda service: service.delete_memory(memory_id))
        self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
