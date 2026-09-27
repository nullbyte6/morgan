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

from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtWidgets import *


class DiffWorkspacePanel(QFrame):
    """A workspace panel for displaying Git diffs with syntax highlighting."""

    close_requested = Signal(str)
    focus_requested = Signal(str)
    move_requested = Signal(str, str)
    title_changed = Signal(str, str)
    diff_updated = Signal(str)  # Emits diff text when updated

    def __init__(
        self,
        panel_id: str,
        title: str = "Git Diff",
        parent: QWidget | None = None):
        super().__init__(parent)

        self.setObjectName("diffWorkspacePanel")
        self.setProperty("diffWorkspacePanel", True)

        # Main scroll area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
        """)

        # Content widget with plain text editor for diff display
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Plain text editor for displaying diff
        self.diff_editor = QPlainTextEdit()
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

        # Set up diff highlighting styles
        self._setup_diff_styles()

        layout.addWidget(self.diff_editor)
        content_widget.setLayout(layout)

        self.scroll_area.setWidget(content_widget)
        self.layout().addWidget(self.scroll_area)

        # Store current diff for dynamic updates
        self.current_diff: str | None = None

    def _setup_diff_styles(self):
        """Set up color styles for diff lines."""
        # Additions (green)
        self.addition_style = QTextCharFormat()
        self.addition_style.setBackground(QColor("#0f5323"))  # Dark green background
        self.addition_style.setForeground(QColor("#7ec86e"))  # Light green text

        # Deletions (red)
        self.deletion_style = QTextCharFormat()
        self.deletion_style.setBackground(QColor("#5c1919"))  # Dark red background
        self.deletion_style.setForeground(QColor("#f14c4c"))  # Light red text

        # Context (default gray)
        self.context_style = QTextCharFormat()
        self.context_style.setForeground(QColor("#d4d4d4"))

        # Header style for file names
        self.header_style = QTextCharFormat()
        self.header_style.setFontWeight(QFont.Bold)
        self.header_style.setForeground(QColor("#9cdcfe"))  # Light blue

    def set_diff(self, diff_text: str) -> None:
        """Set the diff text to display. Supports dynamic updates."""
        if not diff_text:
            return

        self.current_diff = diff_text

        # Parse and format the diff
        formatted_lines = self._parse_and_format_diff(diff_text)

        # Set formatted text to editor
        document = self.diff_editor.document()
        document.setPlainText("\n".join(formatted_lines))

        # Scroll to top when updating
        self.scroll_area.verticalScrollBar().setValue(0)

        # Emit signal for external listeners
        self.diff_updated.emit(diff_text)

    def _parse_and_format_diff(self, diff_text: str) -> list[str]:
        """Parse diff text and apply appropriate formatting."""
        lines = []
        current_block = {"type": "header", "format": self.header_style}
        formatted_lines = []

        for line in diff_text.split("\n"):
            if not line:
                continue

            # Detect diff hunk header (@@ ... @@)
            if line.startswith("@@") or line.startswith("diff ") or \
               line.startswith("index ") or line.startswith("new file") or \
               line.startswith("deleted file") or line.startswith("old mode") or \
               line.startswith("new mode"):
                # New header block
                if current_block["type"] != "header":
                    formatted_lines.append((current_block["format"], "\n".join(current_block["lines"])))
                current_block = {"type": "header", "format": self.header_style, "lines": [line]}
                continue

            # Detect addition lines (+)
            if line.startswith("+") and not line.startswith("+++"):
                current_block["lines"].append(line[1:])  # Remove + prefix
                continue

            # Detect deletion lines (-)
            if line.startswith("-") and not line.startswith("---"):
                current_block["lines"].append(line[1:])  # Remove - prefix
                continue

            # Context or other lines (.)
            current_block["lines"].append(line)

        # Don't forget the last block
        if current_block["type"] != "header":
            formatted_lines.append((current_block["format"], "\n".join(current_block["lines"])))

        # Apply formatting and return
        result = []
        for fmt, text in formatted_lines:
            # For headers, just use plain text
            if fmt == self.header_style:
                result.append(text)
            else:
                # For content lines, apply color based on first character of each line
                for char in text.split("\n"):
                    if not char:
                        continue
                    if char.startswith("+") and not char.startswith("+++"):
                        result.append(f"+{char[1:]}")  # Keep + for visual clarity
                    elif char.startswith("-") and not char.startswith("---"):
                        result.append(f"-{char[1:]}")  # Keep - for visual clarity
                    else:
                        result.append(char)

        return result

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
