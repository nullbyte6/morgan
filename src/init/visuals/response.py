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
"""Streaming Markdown responses displayed inside workspace panels."""

from markdown_it import MarkdownIt
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.lexers.special import TextLexer
from pygments.util import ClassNotFound
from PySide6.QtCore import QTimer, Qt, Slot
from PySide6.QtWidgets import QFrame, QSizePolicy, QTextBrowser, QVBoxLayout, QWidget


class ResponseView(QWidget):
    """An independent, progressively rendered response surface."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("responseView")
        self.setProperty("workspaceViewKey", "response")
        self.setMinimumSize(0, 0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 14)
        layout.setSpacing(0)

        self.document_view = QTextBrowser(self)
        self.document_view.setObjectName("responseDocument")
        self.document_view.setFrameShape(QFrame.NoFrame)
        self.document_view.setReadOnly(True)
        self.document_view.setOpenExternalLinks(True)
        self.document_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.document_view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.document_view.document().setDocumentMargin(8)
        layout.addWidget(self.document_view)

        self._source = ""
        self._render_pending = False
        self._renderer = MarkdownIt(
            "commonmark", {"html": False, "highlight": self._highlight})

    @staticmethod
    def _highlight(code, language, attrs=""):
        try:
            lexer = get_lexer_by_name(language) if language else TextLexer()
        except ClassNotFound:
            lexer = TextLexer()
        return highlight(code, lexer, HtmlFormatter(
            noclasses=True, nowrap=False, style="monokai"))

    @property
    def source(self):
        return self._source

    @Slot(str)
    def append_chunk(self, chunk):
        if not chunk:
            return
        self._source += chunk
        if not self._render_pending:
            self._render_pending = True
            QTimer.singleShot(24, self._render)

    def finish(self, source=None):
        if source is not None:
            self._source = source
        self._render()

    def _render(self):
        self._render_pending = False
        scrollbar = self.document_view.verticalScrollBar()
        follow_tail = scrollbar.value() >= scrollbar.maximum() - 8
        position = scrollbar.value()
        rendered = self._renderer.render(self._source)
        self.document_view.setHtml(
            '<div style="color:#cad3f5; font-family:sans-serif; '
            'font-size:14px; line-height:1.45;">' + rendered + "</div>")
        scrollbar = self.document_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum() if follow_tail else position)
