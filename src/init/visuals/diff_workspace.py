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
"""Git Diff Workspace Panel for Arlo's desktop interface."""
from __future__ import annotations

import uuid

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QFrame, QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget


class DiffWorkspacePanel(QFrame):
    """A workspace panel for displaying Git diffs with syntax highlighting."""

    close_requested = Signal(str)
    focus_requested = Signal(str)
    move_requested = Signal(str, str)
    title_changed = Signal(str, str)
    diff_updated = Signal(str)

    def __init__(
        self,
        panel_id: str,
        title: str = "Git Diff",
        parent: QWidget | None = None):
        super().__init__(parent)

        self.panel_id = panel_id
        self.title = title
        self.setWindowTitle(title)
        self.setObjectName("diffWorkspacePanel")
        self.setProperty("diffWorkspacePanel", True)

        panel_layout = QVBoxLayout(self)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
        """)

        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.diff_editor = QPlainTextEdit()
        self.diff_editor.setReadOnly(True)
        self.diff_editor.setFont(QFont("JetBrains Mono NL", 10))
        self.diff_editor.setStyleSheet("""
            QPlainTextEdit {
                background: #1e1e1e;
                color: #d4d4d4;
                border: none;
                selection-background-color: #264f78;
                padding: 8px;
                font-family: "JetBrains Mono NL", monospace;
            }
        """)

        self._setup_diff_styles()

        layout.addWidget(self.diff_editor)

        self.scroll_area.setWidget(content_widget)
        panel_layout.addWidget(self.scroll_area)
        self.current_diff: str | None = None

    def _setup_diff_styles(self):
        """Set up color styles for diff lines."""
        self.addition_style = QTextCharFormat()
        self.addition_style.setBackground(QColor("#0f5323"))
        self.addition_style.setForeground(QColor("#7ec86e"))

        self.deletion_style = QTextCharFormat()
        self.deletion_style.setBackground(QColor("#5c1919"))
        self.deletion_style.setForeground(QColor("#f14c4c"))

        self.context_style = QTextCharFormat()
        self.context_style.setForeground(QColor("#d4d4d4"))

        self.header_style = QTextCharFormat()
        self.header_style.setFontWeight(QFont.Bold)
        self.header_style.setForeground(QColor("#9cdcfe"))

    def set_diff(self, diff_text: str) -> None:
        """Set the diff text to display. Supports dynamic updates."""
        self.current_diff = diff_text
        formatted_lines = self._parse_and_format_diff(diff_text)
        document = self.diff_editor.document()
        document.clear()
        cursor = QTextCursor(document)
        for index, (line_format, line) in enumerate(formatted_lines):
            if index:
                cursor.insertBlock()
            cursor.insertText(line, line_format)
        self.diff_editor.moveCursor(QTextCursor.Start)
        self.diff_editor.verticalScrollBar().setValue(0)
        self.scroll_area.verticalScrollBar().setValue(0)
        self.diff_updated.emit(diff_text)

    def _parse_and_format_diff(self, diff_text: str) -> list[tuple[QTextCharFormat, str]]:
        """Classify diff lines while preserving their content and prefixes."""
        formatted_lines = []
        in_hunk = False
        for line in diff_text.split("\n"):
            if line.startswith("diff "):
                in_hunk = False
                line_format = self.header_style
            elif line.startswith("@@"):
                in_hunk = True
                line_format = self.header_style
            elif line.startswith("+") and (in_hunk or not line.startswith("+++")):
                line_format = self.addition_style
            elif line.startswith("-") and (in_hunk or not line.startswith("---")):
                line_format = self.deletion_style
            elif not in_hunk and line.startswith((
                "index ", "new file", "deleted file", "old mode", "new mode",
                "---", "+++", "rename from ", "rename to ", "copy from ",
                "copy to ", "similarity index ", "dissimilarity index ",
            )):
                line_format = self.header_style
            else:
                line_format = self.context_style
            formatted_lines.append((line_format, line))
        return formatted_lines

    def update_diff(self, diff_text: str) -> None:
        """Update the displayed diff without closing the panel."""
        self.set_diff(diff_text)

    def closeEvent(self, event) -> None:
        """Handle panel close event."""
        self.current_diff = None
        super().closeEvent(event)


def create_diff_workspace_panel(title: str = "Git Diff", parent=None):
    """Factory function to create a diff workspace panel."""
    panel_id = str(uuid.uuid4())
    return DiffWorkspacePanel(panel_id, title, parent)
