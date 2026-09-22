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
"""Daily Markdown conversation log viewer."""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import *

ENTRY_HEADER = re.compile(
    r"^\[(?P<time>\d{2}:\d{2}:\d{2}) "
    r"(?P<timezone>[+-]\d{4})\]\s*$")

AUTHOR_LINE = re.compile(
    r"^(?P<author>[^\n:]{1,100}):[ \t]?(?P<content>.*)$")

FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")

@dataclass(frozen=True)
class LogMessage:
    timestamp: str
    author: str
    content: str


def parse_log(content: str) -> list[LogMessage]:
    """Parse Arlo's daily Markdown log into individual messages.
    A timestamp is treated as a message delimiter only when followed
    by a valid author line and when outside a fenced code block.
    """
    messages: list[LogMessage] = []
    lines = content.splitlines(keepends=True)
    current_time: str | None = None
    current_author: str | None = None
    current_content: list[str] = []

    fence_char: str | None = None
    fence_length = 0

    def flush() -> None:
        if current_time is None or current_author is None:
            return

        body = "".join(current_content).strip("\n")
        messages.append(
            LogMessage(
                timestamp=current_time,
                author=current_author,
                content=body))

    index = 0

    while index < len(lines):
        line = lines[index]
        stripped = line.rstrip("\r\n")

        if fence_char is None:
            header = ENTRY_HEADER.fullmatch(stripped)

            if header is not None and index + 1 < len(lines):
                author_line = lines[index + 1].rstrip("\r\n")
                author_match = AUTHOR_LINE.fullmatch(author_line)

                if author_match is not None:
                    flush()

                    current_time = header.group("time")
                    current_author = author_match.group("author").strip()
                    current_content = [author_match.group("content")]

                    fence_char = None
                    fence_length = 0

                    index += 2
                    continue

        if current_time is not None:
            current_content.append(line)

        fence_match = FENCE.match(stripped)

        if fence_match is not None:
            marker = fence_match.group(1)

            if fence_char is None:
                fence_char = marker[0]
                fence_length = len(marker)

            elif (
                marker[0] == fence_char
                and len(marker) >= fence_length
                and not stripped[fence_match.end():].strip()):
                fence_char = None
                fence_length = 0

        index += 1

    flush()
    return messages


class LogMessageCard(QFrame):
    """A single conversation entry with Markdown rendering."""
    def __init__(
        self,
        message: LogMessage,
        log_path: Path,
        code_font_family: str,
        parent=None):
        super().__init__(parent)
        self.message = message
        self.log_path = log_path
        self.code_font_family = code_font_family

        self.setObjectName("logMessageCard")
        self.setProperty(
            "role",
            "assistant" if message.author.casefold() == "arlo"
            else "user" if message.author.casefold() != "system"
            else "system")

        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Minimum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        self.author = QLabel(message.author)
        self.author.setObjectName("logMessageAuthor")

        self.timestamp = QLabel(message.timestamp)
        self.timestamp.setObjectName("logMessageTime")

        header.addWidget(self.author)
        header.addWidget(self.timestamp)
        header.addStretch()

        layout.addLayout(header)

        self.body = QTextBrowser(self)
        self.body.setObjectName("logMessageBody")

        self.body.setReadOnly(True)
        self.body.setOpenLinks(False)
        self.body.setOpenExternalLinks(False)

        self.body.setFrameShape(QFrame.Shape.NoFrame)

        self.body.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.body.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed)

        self.body.setDocumentMargin(0)
        self.body.anchorClicked.connect(self.open_link)
        layout.addWidget(self.body)
        self.render_markdown()

    def render_markdown(self) -> None:
        """Render Markdown and apply the dedicated code font."""
        self.body.setMarkdown(self.message.content)
        document = self.body.document()
        block = document.begin()

        while block.isValid():
            block_format = block.blockFormat()

            if block_format.nonBreakableLines():
                block_font = QFont(self.code_font_family)

                cursor = QTextCursor(block)
                cursor.select(QTextCursor.SelectionType.BlockUnderCursor)

                char_format = QTextCharFormat()
                char_format.setFontFamilies(
                    [self.code_font_family])

                cursor.mergeCharFormat(char_format)

            iterator = block.begin()

            while not iterator.atEnd():
                fragment = iterator.fragment()

                if fragment.isValid():
                    fmt = fragment.charFormat()

                    if fmt.fontFixedPitch():
                        cursor = QTextCursor(document)
                        cursor.setPosition(fragment.position())
                        cursor.setPosition(
                            fragment.position() + fragment.length(),
                            QTextCursor.MoveMode.KeepAnchor)

                        code_format = QTextCharFormat()
                        code_format.setFontFamilies(
                            [self.code_font_family])
                        code_format.setFontFixedPitch(True)

                        cursor.mergeCharFormat(code_format)

                iterator += 1

            block = block.next()

        self.update_body_height()

    def update_body_height(self) -> None:
        """Fit the document vertically without nested scrolling."""
        document = self.body.document()
        width = max(1, self.body.viewport().width())
        document.setTextWidth(width)
        height = document.size().height()
        self.body.setFixedHeight(
            max(24, int(height) + 4))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_body_height()

    def open_link(self, url: QUrl) -> None:
        """Open archived code files relative to the daily log."""

        if url.isRelative() or url.scheme() == "":
            target = (self.log_path.parent / url.toString()).resolve()
            try:
                target.relative_to(self.log_path.parent.resolve())
            except ValueError:
                return

            if target.is_file():
                QDesktopServices.openUrl(
                    QUrl.fromLocalFile(str(target)))

            return

        if url.scheme() in ("https", "http"):
            QDesktopServices.openUrl(url)


class LogView(QWidget):
    """Arlo's daily conversation logs."""

    def __init__(self, log_dir: Path, parent=None):
        super().__init__(parent)
        self.log_dir = Path(log_dir)
        self.current_date = datetime.date.today()

        self.last_content: str | None = None
        self.messages: list[LogMessage] = []
        self.code_font_family = "monospace"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 12)
        layout.setSpacing(12)

        header = QHBoxLayout()

        self.title = QLabel(
            self.current_date.strftime("%Y/%m/%d"))
        self.title.setObjectName("logTitle")

        header.addWidget(self.title)
        header.addStretch()

        self.refresh_button = QPushButton("󰑓")
        self.refresh_button.setObjectName("refresh")
        self.refresh_button.setFixedSize(48, 48)
        self.refresh_button.clicked.connect(self.refresh)

        header.addWidget(self.refresh_button)

        layout.addLayout(header)

        self.scroll = QScrollArea(self)
        self.scroll.setObjectName("logScroll")

        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.container = QWidget()
        self.container.setObjectName("logContainer")

        self.message_layout = QVBoxLayout(self.container)
        self.message_layout.setContentsMargins(0, 0, 0, 0)
        self.message_layout.setSpacing(10)

        self.message_layout.addStretch()

        self.scroll.setWidget(self.container)

        layout.addWidget(self.scroll, 1)

        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.refresh)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def clear_messages(self) -> None:
        """Remove all currently displayed cards."""
        while self.message_layout.count() > 1:
            item = self.message_layout.takeAt(0)

            widget = item.widget()

            if widget is not None:
                widget.deleteLater()

        self.messages.clear()

    def append_message(
        self,
        message: LogMessage,
        log_path: Path) -> None:
        """Append one message card above the bottom stretch."""
        card = LogMessageCard(
            message,
            log_path,
            self.code_font_family,
            self.container)

        index = self.message_layout.count() - 1
        self.message_layout.insertWidget(index, card)
        self.messages.append(message)

    def refresh(self) -> None:
        today = datetime.date.today()

        day_changed = today != self.current_date

        if day_changed:
            self.current_date = today
            self.last_content = None
            self.title.setText(
                today.strftime("%Y/%m/%d"))

        path = self.log_dir / f"{today:%Y-%m-%d}.md"
        try:
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            content = ""
        except OSError as error:
            content = f"[Log error]\n{error}"

        if content == self.last_content and not day_changed:
            return

        parsed = parse_log(content)
        scrollbar = self.scroll.verticalScrollBar()
        at_bottom = (scrollbar.value() >= scrollbar.maximum() - 20)
        old_position = scrollbar.value()
        can_append = (
            not day_changed
            and len(parsed) >= len(self.messages)
            and parsed[:len(self.messages)] == self.messages)

        if not can_append:
            self.clear_messages()

        for message in parsed[len(self.messages):]:
            self.append_message(message, path)

        self.last_content = content
        def restore_scroll():
            if at_bottom:
                scrollbar.setValue(scrollbar.maximum())
            else:
                scrollbar.setValue(old_position)

        QTimer.singleShot(0, restore_scroll)