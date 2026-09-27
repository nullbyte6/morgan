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

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPlainTextEdit, QVBoxLayout, QWidget
from pygments.lexers import get_lexer_by_name

from ..editor.highlighter import PygmentsHighlighter


class DiffWorkspacePanel(QFrame):
    """A read-only snapshot of the changes present when a task completes."""

    def __init__(self, directory: str, diff: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("diffWorkspacePanel")
        panel_layout = QVBoxLayout(self)
        panel_layout.setContentsMargins(12, 12, 12, 12)
        panel_layout.setSpacing(10)

        self.status = QLabel(directory, self)
        self.status.setObjectName("diffWorkspaceDirectory")
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        panel_layout.addWidget(self.status)

        self.diff_editor = QPlainTextEdit(self)
        self.diff_editor.setObjectName("diffWorkspaceEditor")
        self.diff_editor.setReadOnly(True)
        self.diff_editor.setUndoRedoEnabled(False)
        self.diff_editor.setAcceptDrops(False)
        self.diff_editor.setFrameShape(QFrame.NoFrame)
        font = QFont(self.font())
        family = QApplication.instance().property("codeFontFamily")
        font.setFamily(family or QFontDatabase.systemFont(QFontDatabase.FixedFont).family())
        font.setStyleHint(QFont.Monospace)
        self.diff_editor.setFont(font)
        self.diff_editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        panel_layout.addWidget(self.diff_editor, 1)
        self.highlighter = PygmentsHighlighter(self.diff_editor.document(), get_lexer_by_name("diff"))
        self.diff_editor.setPlainText(diff)

    def dispose(self):
        self.highlighter.setDocument(None)
