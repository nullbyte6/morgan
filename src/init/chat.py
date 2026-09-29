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
import os
import re
from pathlib import Path

from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtWidgets import *

FILE_TAG_COLOR = QColor("#8aadf4")
FILE_TAG_PATTERN = re.compile(r'(?<!\S)@(?:"([^"\r\n]+)"|([^\s"]+))')
FILE_TAG_QUERY = re.compile(r'(?<!\S)@(?:"([^"\r\n]*)|([^\s"]*))$')
FILE_TAG_TRAILING = ",.;:!?)]}"
FILE_TAG_LIMIT = 50


def _tag_path(base, name):
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        return None
    path = base / name
    return path if os.path.lexists(path) else None


def find_file_tags(text, directory=None):
    base = Path(directory or os.getcwd())
    tags = []
    for match in FILE_TAG_PATTERN.finditer(text):
        if match.group(1) is not None:
            path = _tag_path(base, match.group(1))
            if path is not None:
                tags.append((match.start(), match.end(), match.group(1), path))
            continue
        name = match.group(2)
        while name:
            path = _tag_path(base, name)
            if path is not None:
                tags.append((match.start(), match.start() + 1 + len(name), name, path))
                break
            if name[-1] not in FILE_TAG_TRAILING:
                break
            name = name[:-1]
    return tags


def expand_file_tags(text, directory=None):
    tags = {}
    for _start, _end, name, path in find_file_tags(text, directory):
        tags.setdefault(name, path)
    if not tags:
        return text
    lines = [f"- @{name}: {path} ({'directory' if path.is_dir() else 'file'})"
             for name, path in tags.items()]
    return (text + "\n\nTagged paths from the current working directory:\n"
            + "\n".join(lines))


class FileTagHighlighter(QSyntaxHighlighter):
    def highlightBlock(self, text):
        tag_format = QTextCharFormat()
        tag_format.setForeground(FILE_TAG_COLOR)
        for start, end, _name, _path in find_file_tags(text):
            self.setFormat(start, end - start, tag_format)


class FileTagPopup(QListWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("fileTagResults")
        self.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.ElideRight)
        self.setUniformItemSizes(True)


class ChatInput(QTextEdit):
    submitted = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.min_lines = 1
        self.max_lines = 4
        self.setAcceptRichText(False)
        self.document().setDocumentMargin(0)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.file_tag_highlighter = FileTagHighlighter(self.document())
        self.file_tag_popup = FileTagPopup(self)
        self.file_tag_popup.itemClicked.connect(self.accept_file_tag)
        self.file_tag_start = -1
        self.file_tag_directory = os.getcwd()

        # Conectar señales de cambio de contenido para ajustar altura
        self.textChanged.connect(self.adjust_height)
        self.document().documentLayout().documentSizeChanged.connect(
            self.adjust_height)
        self.textChanged.connect(self.update_file_tags)
        self.cursorPositionChanged.connect(self.update_file_tags)
        self.adjust_height()

    def adjust_height(self, *_):
        line_height = self.fontMetrics().lineSpacing()
        content_height = self.document().size().height()

        # Calcular altura basada en líneas visibles (incluyendo wrapping)
        max_height = self.max_lines * line_height

        # Altura mínima para una línea, máxima para 4 líneas
        height = max(line_height, min(max_height, int(content_height)))
        self.setFixedHeight(height)

    def refresh_file_tags(self):
        directory = os.getcwd()
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
        if cursor.hasSelection() or not self.hasFocus():
            self.hide_file_tags()
            return
        block = cursor.block()
        match = FILE_TAG_QUERY.search(block.text()[:cursor.positionInBlock()])
        if match is None:
            self.hide_file_tags()
            return
        query = (match.group(1) if match.group(1) is not None else match.group(2)).casefold()
        try:
            entries = [(entry.name, entry.is_dir()) for entry in os.scandir(os.getcwd())]
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
        rows = min(popup.count(), 8)
        height = popup.sizeHintForRow(0) * rows + popup.frameWidth() * 2 + 8
        width = max(240, min(420, self.width()))
        popup.resize(width, height)
        anchor = self.cursorRect(self.textCursor())
        point = self.viewport().mapToGlobal(anchor.topLeft())
        screen = QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = min(max(point.x(), area.left()), area.right() - width)
        y = point.y() - height - 6
        if y < area.top():
            y = self.viewport().mapToGlobal(anchor.bottomLeft()).y() + 6
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

    def focusOutEvent(self, event):
        self.hide_file_tags()
        super().focusOutEvent(event)

    def keyPressEvent(self, event):
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
