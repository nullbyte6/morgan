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
"""Log messages: parsing Morgan's daily Markdown log and showing each message as a card."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QFontDatabase, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QTextBrowser, QVBoxLayout)

from src.init.config import DEFAULTS
from src.init.identity import get_assistant_name
from src.init.lang import tr

ENTRY_HEADER = re.compile(
    r"^\[(?:\d{4}-\d{2}-\d{2}[ T])?"
    r"(?P<time>\d{2}:\d{2}:\d{2})"
    r"(?:\s+(?:Z|[+-]\d{2}:?\d{2}))?]\s*$")

AUTHOR_LINE = re.compile(
    r"^(?P<author>[^\n:]{1,100}):[ \t]?(?P<content>.*)$")

FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")
COPY_GLYPH = ""
COPIED_GLYPH = ""
COPIED_MS = 1200
REMOVE_GLYPH = ""
ARMED_MS = 3000

@dataclass(frozen=True)
class LogMessage:
    timestamp: str
    author: str
    content: str
    role: str = ""
    id: str = ""


def parse_log(content: str) -> list[LogMessage]:
    """Parse Morgan's daily Markdown log into individual messages.
    A timestamp is treated as a message delimiter only when followed
    by a valid author line and when outside a fenced code block.
    """
    messages: list[LogMessage] = []
    lines = content.splitlines(keepends=True)
    assistant_names = {get_assistant_name().casefold(), DEFAULTS["assistant"]["name"].casefold()}
    header = re.match(r"^(.*?) Log ", lines[0]) if lines else None
    if header is not None:
        assistant_names.add(header.group(1).casefold())
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
                content=body,
                role="assistant" if current_author.casefold() in assistant_names
                else "system" if current_author.casefold() == "system" else "user"))

    index = 0

    while index < len(lines):
        line = lines[index]
        stripped = line.rstrip("\r\n")

        if fence_char is None:
            header = ENTRY_HEADER.fullmatch(stripped)

            author_index = index + 1
            if header is not None:
                while (author_index < len(lines)
                       and not lines[author_index].strip()):
                    author_index += 1

            if header is not None and author_index < len(lines):
                author_line = lines[author_index].rstrip("\r\n")
                author_match = AUTHOR_LINE.fullmatch(author_line)

                if author_match is not None:
                    flush()

                    current_time = header.group("time")
                    current_author = author_match.group("author").strip()
                    current_content = [author_match.group("content")]

                    fence_char = None
                    fence_length = 0

                    index = author_index + 1
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


class RemoveButton(QPushButton):
    """A trash button that arms on the first click and asks for a second one before removing."""

    confirmed = Signal()

    def __init__(self, font_family: str, parent=None, tooltips: tuple[str, str] = ("nova.diary.remove",
                                                                                 "nova.diary.remove_confirm")):
        super().__init__(REMOVE_GLYPH, parent)
        self.tooltips = tooltips
        self.setObjectName("logRemoveNav")
        icon_font = QFont(font_family)
        icon_font.setPixelSize(16)
        self.setFont(icon_font)
        self.setFixedSize(24, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.disarm_timer = QTimer(self)
        self.disarm_timer.setSingleShot(True)
        self.disarm_timer.setInterval(ARMED_MS)
        self.disarm_timer.timeout.connect(lambda: self.set_armed(False))
        self.clicked.connect(self.press)
        self.set_armed(False)

    def set_armed(self, armed: bool) -> None:
        self.setProperty("armed", armed)
        self.setToolTip(tr(self.tooltips[1] if armed else self.tooltips[0]))
        self.style().unpolish(self)
        self.style().polish(self)

    def press(self) -> None:
        if self.property("armed"):
            self.disarm_timer.stop()
            self.set_armed(False)
            self.confirmed.emit()
            return
        self.set_armed(True)
        self.disarm_timer.start()


class LogMessageCard(QFrame):
    """A single conversation entry with Markdown rendering."""

    removed = Signal(object)

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
            message.role or ("assistant" if message.author.casefold() in {get_assistant_name().casefold(), DEFAULTS["assistant"]["name"].casefold()}
            else "user" if message.author.casefold() != "system"
            else "system"))

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

        self.copy_button = QPushButton(COPY_GLYPH)
        self.copy_button.setObjectName("logCopyNav")

        icon_font = QFont(self.code_font_family)
        icon_font.setPixelSize(16)

        self.copy_button.setFont(icon_font)
        self.copy_button.setFixedSize(24, 24)
        self.copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_button.clicked.connect(self.copy_log)
        self.copy_reset = QTimer(self)
        self.copy_reset.setSingleShot(True)
        self.copy_reset.setInterval(COPIED_MS)
        self.copy_reset.timeout.connect(lambda: self.copy_button.setText(COPY_GLYPH))

        header.addWidget(self.author)
        header.addWidget(self.timestamp)
        header.addStretch(1)
        header.addWidget(self.copy_button, 0, Qt.AlignmentFlag.AlignTop)
        if message.id:
            self.remove_button = RemoveButton(self.code_font_family)
            self.remove_button.confirmed.connect(lambda: self.removed.emit(self.message))
            header.addWidget(self.remove_button, 0, Qt.AlignmentFlag.AlignTop)

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

        self.body.document().setDocumentMargin(0)
        self.body.anchorClicked.connect(self.open_link)
        layout.addWidget(self.body)
        self.render_markdown()

    def copy_log(self) -> None:
        """Copy the original Markdown content of this message."""
        clipboard = QApplication.clipboard()
        clipboard.setText(self.message.content)
        self.copy_button.setText(COPIED_GLYPH)
        self.copy_reset.start()

    def render_markdown(self) -> None:
        """Render Markdown and apply the dedicated code font."""
        self.body.setMarkdown(self.message.content)
        document = self.body.document()
        block = document.begin()

        while block.isValid():
            block_format = block.blockFormat()

            if block_format.nonBreakableLines():
                cursor = QTextCursor(block)
                cursor.select(QTextCursor.SelectionType.BlockUnderCursor)

                char_format = QTextCharFormat()
                char_format.setFont(QFont(self.code_font_family))
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
                        code_format.setFont(QFont(self.code_font_family))
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
            from src.init.visuals.gateway import open_url
            try:
                open_url(url.toString())
            except (RuntimeError, ValueError) as error:
                self.body.setToolTip(str(error))


def code_font_family() -> str:
    """The installed JetBrains Mono family used for code in messages."""
    return next((family for family in QFontDatabase.families() if "jetbrains" in family.casefold()),
                "JetBrains Mono NL")
