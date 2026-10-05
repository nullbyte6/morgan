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
import os
import re

from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtWidgets import *

from .file_tags import (FILE_TAG_LIMIT, FILE_TAG_QUERY, expand_file_tags,
                        find_file_tags)
from .theme import current_theme, on_theme_changed


class FileTagHighlighter(QSyntaxHighlighter):
    def __init__(self, document, directory=os.getcwd):
        super().__init__(document)
        self.directory = directory
        on_theme_changed(self.apply_theme)

    def apply_theme(self, theme):
        self.rehighlight()

    def highlightBlock(self, text):
        tag_format = QTextCharFormat()
        tag_format.setForeground(current_theme().color("file_tag"))
        for start, end, _name, _path in find_file_tags(text, self.directory()):
            self.setFormat(start, end - start, tag_format)


class FileTagPopup(QListWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("fileTagResults")
        self.setFocusPolicy(Qt.NoFocus)
        self.hide()
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.ElideRight)
        self.setUniformItemSizes(True)


class ChatInput(QTextEdit):
    submitted = Signal()

    def __init__(self, parent=None, directory=os.getcwd):
        super().__init__(parent)
        self.directory = directory
        self.min_lines = 1
        self.max_lines = 4
        self.setAcceptRichText(False)
        self.document().setDocumentMargin(0)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.file_tag_highlighter = FileTagHighlighter(self.document(), self.directory)
        self.file_tag_popup = FileTagPopup(self)
        self.file_tag_popup.itemClicked.connect(self.accept_file_tag)
        self.file_tag_start = -1
        self.file_tag_directory = self.directory()
        self.history = []
        self.history_index = None
        self.history_draft = ""

        self.textChanged.connect(self.adjust_height)
        self.document().documentLayout().documentSizeChanged.connect(
            self.adjust_height)
        self.textChanged.connect(self.update_file_tags)
        self.cursorPositionChanged.connect(self.update_file_tags)
        self.adjust_height()

    def adjust_height(self, *_):
        line_height = self.fontMetrics().lineSpacing()
        content_height = self.document().size().height()

        max_height = self.max_lines * line_height

        height = max(line_height, min(max_height, int(content_height)))
        self.setFixedHeight(height)

    def refresh_file_tags(self):
        directory = self.directory()
        if directory == self.file_tag_directory:
            return
        self.file_tag_directory = directory
        self.file_tag_highlighter.rehighlight()
        self.update_file_tags()

    def hide_file_tags(self):
        self.file_tag_start = -1
        self.file_tag_popup.hide()

    def update_file_tags(self):
        cursor = self.textCursor()
        if (not getattr(self, "file_tags_enabled", True)
                or cursor.hasSelection() or not self.hasFocus()):
            self.hide_file_tags()
            return
        block = cursor.block()
        match = FILE_TAG_QUERY.search(block.text()[:cursor.positionInBlock()])
        if match is None:
            self.hide_file_tags()
            return
        query = (match.group(1) if match.group(1) is not None else match.group(2)).casefold()
        try:
            entries = [(entry.name, entry.is_dir()) for entry in os.scandir(self.directory())]
        except OSError:
            entries = []
        matches = [entry for entry in entries if query in entry[0].casefold()]
        matches.sort(key=lambda entry: (not entry[0].casefold().startswith(query),
                                        not entry[1], entry[0].casefold()))
        if not matches:
            self.hide_file_tags()
            return
        self.file_tag_start = block.position() + match.start()
        popup = self.file_tag_popup
        popup.clear()
        for name, is_dir in matches[:FILE_TAG_LIMIT]:
            item = QListWidgetItem(name + ("/" if is_dir else ""))
            item.setData(Qt.UserRole, name)
            popup.addItem(item)
        popup.setCurrentRow(0)
        self.position_file_tags()

    def position_file_tags(self):
        popup = self.file_tag_popup
        host = self.window()
        if popup.parentWidget() is not host:
            popup.setParent(host)
            popup.setFocusPolicy(Qt.NoFocus)
        rows = min(popup.count(), 8)
        height = popup.sizeHintForRow(0) * rows + popup.frameWidth() * 2 + 8
        width = max(240, min(420, self.width()))
        popup.resize(width, height)
        anchor = self.cursorRect(self.textCursor())
        point = self.viewport().mapTo(host, anchor.topLeft())
        area = host.rect()
        x = max(area.left(), min(point.x(), area.right() - width))
        y = point.y() - height - 6
        if y < area.top():
            y = self.viewport().mapTo(host, anchor.bottomLeft()).y() + 6
        popup.move(x, y)
        popup.show()
        popup.raise_()

    def accept_file_tag(self, item=None):
        item = item or self.file_tag_popup.currentItem()
        if item is None or self.file_tag_start < 0:
            self.hide_file_tags()
            return
        name = item.data(Qt.UserRole)
        cursor = self.textCursor()
        cursor.setPosition(self.file_tag_start)
        cursor.setPosition(self.textCursor().position(), QTextCursor.KeepAnchor)
        tag = f'@"{name}"' if re.search(r'[\s"]', name) else f"@{name}"
        self.hide_file_tags()
        cursor.insertText(tag + " ")
        self.setTextCursor(cursor)
        self.setFocus()

    def remember(self):
        text = self.toPlainText().strip()
        self.history_index = None
        if text and (not self.history or self.history[-1] != text):
            self.history.append(text)

    def browse_history(self, step):
        if not self.history:
            return
        if self.history_index is None:
            if step > 0:
                return
            self.history_draft = self.toPlainText()
            index = len(self.history) - 1
        else:
            index = self.history_index + step
            if index < 0:
                return
        if index >= len(self.history):
            self.history_index = None
            text = self.history_draft
        else:
            self.history_index = index
            text = self.history[index]
        self.setPlainText(text)
        self.moveCursor(QTextCursor.End)
        self.hide_file_tags()

    def focusOutEvent(self, event):
        self.hide_file_tags()
        super().focusOutEvent(event)

    def keyPressEvent(self, event):
        if (event.modifiers() & Qt.AltModifier and event.key() in (Qt.Key_Up, Qt.Key_Down)
                and not event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier)):
            event.accept()
            self.browse_history(-1 if event.key() == Qt.Key_Up else 1)
            return

        popup = self.file_tag_popup
        if popup.isVisible():
            key = event.key()
            if key in (Qt.Key_Up, Qt.Key_Down):
                step = -1 if key == Qt.Key_Up else 1
                popup.setCurrentRow((popup.currentRow() + step) % popup.count())
                event.accept()
                return
            if key in (Qt.Key_Tab, Qt.Key_Return, Qt.Key_Enter):
                event.accept()
                self.accept_file_tag()
                return
            if key == Qt.Key_Escape:
                event.accept()
                self.hide_file_tags()
                return

        if event.key() in (Qt.Key_Return,
                           Qt.Key_Enter) and not event.modifiers() & Qt.ShiftModifier:
            event.accept()
            self.submitted.emit()
            return

        super().keyPressEvent(event)
