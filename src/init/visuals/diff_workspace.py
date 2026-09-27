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
import os

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .file_viewer import FileTask


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

        self.directory = os.getcwd()
        self._task = None
        self._disposed = False
        toolbar = QHBoxLayout()
        self.reload_button = QPushButton("Reload", self)
        self.reload_button.clicked.connect(self.reload)
        toolbar.addWidget(self.reload_button)
        toolbar.addStretch()
        panel_layout.addLayout(toolbar)
        self.status = QLabel(self.directory, self)
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        panel_layout.addWidget(self.status)

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
                background: #24273a;
                color: #cad3f5;
                border: none;
                selection-background-color: #494d64;
                padding: 8px;
                font-family: "JetBrains Mono NL", monospace;
            }
        """)

        self._setup_diff_styles()

        layout.addWidget(self.diff_editor)

        self.scroll_area.setWidget(content_widget)
        panel_layout.addWidget(self.scroll_area)
        self.current_diff: str | None = None
        QTimer.singleShot(0, self.reload)

    def set_directory(self, directory):
        if directory != self.directory:
            self.directory = directory
            self.reload()

    def reload(self):
        if self._disposed:
            return
        if self._task is not None:
            self._task.cancelled.set()
        directory = self.directory
        self.status.setText(directory + "\nLoading…")
        self.reload_button.setEnabled(False)

        def load(cancelled):
            from src.init.brain import git_diff, git_status
            from src.init.task_outcomes import Outcome
            patches = []
            status = git_status(directory)
            if status["outcome"] != Outcome.SUCCESS:
                data = status.get("data", {})
                return {"error": (data.get("stderr") or str(data)) if isinstance(data, dict) else str(data)}
            for staged in (True, False):
                if cancelled.is_set():
                    return None
                result = git_diff(repository=directory, staged=staged)
                if result["outcome"] not in {Outcome.SUCCESS, Outcome.NEGATIVE}:
                    data = result.get("data", {})
                    return {"error": (data.get("stderr") or str(data)) if isinstance(data, dict) else str(data)}
                patch = result["data"]["stdout"]
                if patch:
                    patches.append(("Staged changes" if staged else "Working tree changes") + "\n" + patch)
            return {"directory": directory, "status": status["data"]["stdout"], "diff": "\n".join(patches)}

        self._task = FileTask(self, load)

    def loaded(self, result):
        self.reload_button.setEnabled(True)
        if not result:
            return
        if result.get("error"):
            self.status.setText(self.directory + "\n" + result["error"])
            self.set_diff("")
            return
        self.status.setText(result["directory"] + "\n" + result["status"].strip())
        self.set_diff(result["diff"] or "No differences in tracked files.")

    def dispose(self):
        self._disposed = True
        if self._task is not None:
            self._task.cancelled.set()

    def _setup_diff_styles(self):
        """Set up color styles for diff lines."""
        self.addition_style = QTextCharFormat()
        self.addition_style.setBackground(QColor("#36463a"))
        self.addition_style.setForeground(QColor("#a6da95"))

        self.deletion_style = QTextCharFormat()
        self.deletion_style.setBackground(QColor("#503640"))
        self.deletion_style.setForeground(QColor("#ed8796"))

        self.context_style = QTextCharFormat()
        self.context_style.setForeground(QColor("#cad3f5"))

        self.header_style = QTextCharFormat()
        self.header_style.setFontWeight(QFont.Bold)
        self.header_style.setForeground(QColor("#8aadf4"))

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
