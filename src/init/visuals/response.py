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
"""Streaming Markdown responses displayed inside workspace panels."""

from src.init.identity import get_assistant_name

import threading
from dataclasses import dataclass, field

from markdown_it import MarkdownIt
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.lexers.special import TextLexer
from pygments.util import ClassNotFound
from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtWidgets import (QApplication, QFrame, QSizePolicy,
                               QTextBrowser, QVBoxLayout, QWidget)

from ..editor.highlighter import pygments_style
from ..theme import current_theme, on_theme_changed


@dataclass(eq=False)
class ResponseRequest:
    title: str
    owner: object = None
    completed: threading.Event = field(default_factory=threading.Event)
    result: str | None = None
    error: str | None = None


_registry_lock = threading.Lock()
_bridge = None


class ResponseBridge(QObject):
    requested = Signal(object)

    def __init__(self, parent):
        global _bridge
        app = QApplication.instance()
        if app is None or QThread.currentThread() != app.thread():
            raise RuntimeError("ResponseBridge requires the GUI thread")
        super().__init__(parent)
        self._lock = threading.Lock()
        self._pending = set()
        self._closed = False
        self.requested.connect(self._open, Qt.QueuedConnection)
        app.aboutToQuit.connect(self.shutdown)
        with _registry_lock:
            _bridge = self

    def request(self, title: str, owner=None) -> str:
        request = ResponseRequest(title.strip() or "Response", owner)
        with self._lock:
            if self._closed:
                raise RuntimeError(f"{get_assistant_name()}'s response workspace is unavailable")
            self._pending.add(request)
        try:
            if QThread.currentThread() == self.thread():
                self._open(request)
            else:
                self.requested.emit(request)
            if not request.completed.wait(15):
                with self._lock:
                    if not request.completed.is_set():
                        self._complete(request, error="Response workspace opening timed out")
        except Exception as error:
            with self._lock:
                self._complete(request, error=str(error))
        if request.error:
            raise RuntimeError(request.error)
        return request.result

    def _complete(self, request, *, result=None, error=None):
        if request.completed.is_set():
            return
        request.result = result
        request.error = error
        self._pending.discard(request)
        request.completed.set()

    @Slot(object)
    def _open(self, request):
        with self._lock:
            if self._closed or request.completed.is_set():
                return
            try:
                window = self.parent()
                workspace = window.workspace
                session = window.session_for(request.owner)
                current = session.current_response_view
                panel = next(
                    (workspace.get_panel(panel_id)
                     for panel_id in workspace.panel_ids
                     if workspace.get_panel(panel_id) is not None
                     and workspace.get_panel(panel_id).content is current
                     and panel_id not in workspace._closing_panels
                     and panel_id not in workspace._pending_closes),
                    None)
                if panel is not None:
                    workspace.focus_panel(panel.panel_id)
                    window.restore_from_mascot()
                    self._complete(request, result="Response workspace is already open.")
                    return

                view = ResponseView()
                panel_id = workspace.open_panel(
                    title=request.title,
                    content=view,
                    target_id=session.panel_id or window.main_workspace_panel_id,
                    direction=Qt.Key_Right,
                )

                session.current_response_view = view
                view.destroyed.connect(
                    lambda: window._forget_response_view(view))
                workspace.focus_panel(panel_id)
                window.restore_from_mascot()
                self._complete(request, result="Response workspace opened.")
            except Exception as error:
                self._complete(request, error=str(error))

    @Slot()
    def shutdown(self):
        global _bridge
        with _registry_lock:
            if _bridge is self:
                _bridge = None
        with self._lock:
            self._closed = True
            for request in tuple(self._pending):
                self._complete(request, error=f"{get_assistant_name()}'s response workspace was closed")


def request_response_workspace(title: str = "Response", owner=None) -> str:
    with _registry_lock:
        bridge = _bridge
    if bridge is None:
        raise RuntimeError(f"The response workspace requires the running {get_assistant_name()} desktop")
    return bridge.request(title, owner)

class ResponseView(QWidget):
    """An independent, progressively rendered response surface."""

    DOCUMENT_CSS = """
            code {
                font-family: "JetBrains Mono NL", "JetBrains Mono", monospace;
                font-size: 12px;
                color: @code_inline_text;
                background-color: @code_inline_background;
            }

            pre {
                font-family: "JetBrains Mono NL", "JetBrains Mono", monospace;
                font-size: 12px;
            }

            table {
                border-collapse: collapse;
                margin: 12px 0;
            }

            th, td {
                border: 1px solid @table_border;
                padding: 6px 10px;
                vertical-align: top;
            }

            th {
                background-color: @table_header_background;
                color: @table_header_text;
            }

            tr:nth-child(even) {
                background-color: @table_row_alternate;
            }"""

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
        self.document_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.document_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.document_view.document().setDocumentMargin(8)
        self.document_view.document().setDefaultStyleSheet(
            current_theme().render(self.DOCUMENT_CSS))
        layout.addWidget(self.document_view)

        self._source = ""
        self._render_pending = False
        self._renderer = MarkdownIt(
            "commonmark", {"html": False, "highlight": self._highlight})
        self._renderer.enable("table")
        on_theme_changed(self.apply_theme)

    def apply_theme(self, theme):
        self.document_view.document().setDefaultStyleSheet(theme.render(self.DOCUMENT_CSS))
        self._render()

    def _highlight(self, code: str, language: str, attrs: str = "") -> str:
        try:
            lexer = get_lexer_by_name((language or "text").strip(),
                                      stripall=False)
        except ClassNotFound:
            lexer = TextLexer(stripall=False)

        theme = current_theme()
        formatter = HtmlFormatter(noclasses=True, nowrap=True, style=pygments_style(theme))
        highlighted = highlight(code, lexer, formatter)

        return (
            theme.render('<pre style="background-color:@code_block_background; '
                         'color:@code_block_text; border:2px solid @code_block_border; ')
            + 'padding:12px 14px; margin:10px 0; '
            "font-family:'JetBrains Mono NL', 'JetBrains Mono', monospace; "
            'font-size:12px; white-space:pre-wrap;">'
            + highlighted
            + '</pre>'
        )

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
            f'<div style="color:{current_theme().hex("text")}; font-size:14px; line-height:1.45;">'
            + rendered + "</div>")
        scrollbar = self.document_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum() if follow_tail else position)
