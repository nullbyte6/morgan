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
"""Read-only, bounded workspace file inspection and extensible view factories."""
from __future__ import annotations

import codecs
import mimetypes
import os
import stat
import weakref
from pathlib import Path
from threading import Event

from PySide6.QtCore import (
    QFileSystemWatcher, QObject, QRect, QSize, Qt, QRunnable, QThreadPool,
    Signal, Slot)
from PySide6.QtGui import QFont, QPainter, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)
from shiboken6 import isValid

from src.init import hotkeys

from ..attachments import TEXT_EXTENSIONS, _encoding
from ..editor.highlighter import PygmentsHighlighter, lexer_for_path
from ..editor.live import LineNumberArea
from ..theme import current_theme, on_theme_changed

TEXT_BYTE_LIMIT = 1024 * 1024
TEXT_LINE_LIMIT = 20000
TEXT_COLUMN_LIMIT = 32768
MARKDOWN_PREVIEW_LIMIT = 128 * 1024


class ViewerRegistry:
    """Factories own support policy; the drop router knows no file formats."""

    def __init__(self):
        self.factories = []

    def register(self, factory):
        self.factories.append(factory)

    def factory_for(self, path):
        return next((factory for factory in self.factories
                     if factory.supports(path)), None)

    def supports(self, path):
        return self.factory_for(path) is not None

    def create(self, path):
        factory = self.factory_for(path)
        if factory is None:
            raise ValueError("Unsupported file type")
        return factory(path)


class _FileRunner(QRunnable):
    def __init__(self, task, operation):
        super().__init__()
        self.task, self.operation = task, operation

    def run(self):
        try:
            result = self.operation(self.task.cancelled)
        except FileNotFoundError:
            result = {"error": "File no longer exists"}
        except UnicodeError:
            result = {"error": "Unable to decode file"}
        except (OSError, ValueError) as error:
            result = {"error": str(error) or "Unable to read file"}
        except Exception:
            result = {"error": "Unable to load file"}
        self.task.finished.emit(result)


class FileTask(QObject):
    """An application-owned delivery guard outlives a closed loading surface."""
    finished = Signal(object)

    def __init__(self, viewer, operation):
        app = QApplication.instance()
        super().__init__(app)
        self.viewer = weakref.ref(viewer)
        self.cancelled = Event()
        self.finished.connect(self._deliver, Qt.QueuedConnection)
        app.aboutToQuit.connect(self.cancelled.set)
        viewer.destroyed.connect(self.cancelled.set)
        QThreadPool.globalInstance().start(_FileRunner(self, operation))

    @Slot(object)
    def _deliver(self, result):
        viewer = self.viewer()
        try:
            if (not self.cancelled.is_set() and viewer is not None
                    and isValid(viewer) and viewer._task is self):
                viewer._task = None
                viewer.loaded(result)
            elif result and result.get("document") is not None:
                result["document"].deleteLater()
        finally:
            self.deleteLater()


def file_snapshot(path):
    info = os.stat(path)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("Only regular files can be viewed")
    return info.st_size, info.st_mtime_ns


def read_text_preview(path, cancelled):
    snapshot = file_snapshot(path)
    with open(path, "rb") as stream:
        sample = stream.read(4096)
        encoding = _encoding(sample)
        stream.seek(0)
        decoder = codecs.getincrementaldecoder(encoding)()
        parts, consumed = [], 0
        while consumed < min(snapshot[0], TEXT_BYTE_LIMIT):
            if cancelled.is_set():
                return None
            data = stream.read(min(65536, TEXT_BYTE_LIMIT - consumed))
            if not data:
                break
            consumed += len(data)
            parts.append(decoder.decode(data, final=consumed >= snapshot[0]))
    text = "".join(parts).lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if "\x00" in text or any(ord(c) < 9 or 13 < ord(c) < 32 for c in text):
        raise ValueError("Binary content is not supported as text")
    reason = "" if consumed >= snapshot[0] else "first 1 MiB"
    lines = text.split("\n")
    if len(lines) > TEXT_LINE_LIMIT:
        lines = lines[:TEXT_LINE_LIMIT]
        reason = "first 20,000 lines"
    for index, line in enumerate(lines):
        if len(line) > TEXT_COLUMN_LIMIT:
            lines = lines[:index] + [line[:TEXT_COLUMN_LIMIT]]
            reason = "line length limit (32,768 characters)"
            break
    if file_snapshot(path) != snapshot:
        raise ValueError("File changed while loading; reload to try again")
    return {"text": "\n".join(lines), "snapshot": snapshot,
            "partial": bool(reason), "reason": reason, "encoding": encoding}


class FileViewer(QWidget):
    """Shared lifetime, reload and external-change state without model access."""

    def __init__(self, path):
        super().__init__()
        self.path = os.path.abspath(path)
        self._task = None
        self._snapshot = None
        self._load_notice = ""
        self._disposed = False
        self.setObjectName("workspaceFileViewer")
        self.setProperty("workspaceViewKey", "file")
        self.setMinimumSize(0, 0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.setToolTip(self.path)
        self.layout_box = QVBoxLayout(self)
        self.layout_box.setSizeConstraint(QVBoxLayout.SetNoConstraint)
        self.layout_box.setContentsMargins(6, 4, 6, 6)
        self.layout_box.setSpacing(6)
        self.toolbar = QHBoxLayout()
        self.toolbar.setSpacing(4)
        self.reload_button = QPushButton("Reload", self)
        self.reload_button.setToolTip("Reload the file from disk")
        self.reload_button.clicked.connect(self.reload)
        self.toolbar.addWidget(self.reload_button)
        self.layout_box.addLayout(self.toolbar)
        self.status = QLabel("Loading…", self)
        self.status.setObjectName("fileViewerStatus")
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        self.status.setMinimumWidth(0)
        self.layout_box.addWidget(self.status)
        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self._external_change)
        self.watcher.directoryChanged.connect(self._external_change)

    def start_load(self, operation):
        if self._disposed:
            return
        if self._task is not None:
            self._task.cancelled.set()
        self.show_state("Loading…")
        self.reload_button.setEnabled(False)
        self._task = FileTask(self, operation)

    def loaded(self, result):
        self.reload_button.setEnabled(True)
        if not result or result.get("error"):
            self.show_state((result or {}).get("error", "Unable to load file"))
            return False
        self._snapshot = result["snapshot"]
        watched = self.watcher.files() + self.watcher.directories()
        if watched:
            self.watcher.removePaths(watched)
        self.watcher.addPaths([self.path, str(Path(self.path).parent)])
        self._external_change()
        return True

    def show_state(self, message):
        self.status.setText("\n".join(part for part in (message, self._load_notice) if part))

    def _external_change(self, *_):
        if self._disposed or self._snapshot is None:
            return
        try:
            changed = file_snapshot(self.path) != self._snapshot
        except FileNotFoundError:
            self.show_state("File no longer exists · Showing the loaded snapshot")
            return
        except (OSError, ValueError):
            self.show_state("File is no longer readable · Showing the loaded snapshot")
            return
        if changed:
            self.show_state("File changed externally · Reload to update the view")

    def context_snapshot(self):
        return {"path": self.path}

    def reload(self):
        raise NotImplementedError

    def dispose(self):
        self._disposed = True
        if self._task is not None:
            self._task.cancelled.set()
        watched = self.watcher.files() + self.watcher.directories()
        if watched:
            self.watcher.removePaths(watched)


class SourceSurface(QPlainTextEdit):
    """Selection, native copying and a reused gutter, with no write API."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("fileViewerSource")
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self.setAcceptDrops(False)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMinimumSize(0, 0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        font = QFont("JetBrainsMonoNL NFM", 11)
        font.setFamilies(["JetBrainsMonoNL NFM", "JetBrains Mono NL", "monospace"])
        font.setStyleHint(QFont.Monospace)
        self.setFont(font)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self.line_area = LineNumberArea(self)
        self.blockCountChanged.connect(self.update_line_area_width)
        self.updateRequest.connect(self.update_line_area)
        self.update_line_area_width()
        on_theme_changed(self.apply_theme)

    def apply_theme(self, theme):
        self.line_area.update()

    def line_area_width(self):
        return 16 + self.fontMetrics().horizontalAdvance("9") * len(str(self.blockCount()))

    def update_line_area_width(self, *_):
        width = self.line_area_width()
        self.setViewportMargins(width, 0, 0, 0)
        self.line_area.setGeometry(QRect(0, 0, width, self.height()))

    def update_line_area(self, rect, dy):
        if dy:
            self.line_area.scroll(0, dy)
        else:
            self.line_area.update(0, rect.y(), self.line_area.width(), rect.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_line_area_width()

    def paint_line_numbers(self, event):
        painter = QPainter(self.line_area)
        theme = current_theme()
        painter.fillRect(event.rect(), theme.color("surface"))
        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        while block.isValid() and top <= event.rect().bottom():
            height = round(self.blockBoundingRect(block).height())
            if block.isVisible() and top + height >= event.rect().top():
                painter.setPen(theme.color("line_number"))
                painter.drawText(0, top, self.line_area.width() - 7, height,
                                 Qt.AlignRight | Qt.AlignVCenter, str(block.blockNumber() + 1))
            top += height
            block = block.next()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ShiftModifier:
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - event.angleDelta().y())
            event.accept()
            return
        super().wheelEvent(event)


class TextViewer(FileViewer):
    @staticmethod
    def supports(path):
        name = Path(path)
        mime = mimetypes.guess_type(str(name))[0] or ""
        return (name.suffix.lower() in TEXT_EXTENSIONS | {".kts"}
                or name.name.lower() in TEXT_EXTENSIONS
                or mime.startswith("text/")
                or mime in {"application/json", "application/xml", "application/javascript"})

    def __init__(self, path):
        super().__init__(path)
        self.highlighter = None
        self.preview = None
        self._text = ""
        self._partial = False
        self.stack = QStackedWidget(self)
        self.stack.setMinimumSize(0, 0)
        self.stack.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.source = SourceSurface(self)
        self.stack.addWidget(self.source)
        self.layout_box.addWidget(self.stack, 1)
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Find in loaded text · Enter for next")
        self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(self.find_next)
        self.search.hide()
        self.layout_box.insertWidget(1, self.search)
        self.find_shortcut = hotkeys.bind("find", self, self.show_search, Qt.WidgetWithChildrenShortcut)
        self.escape_shortcut = hotkeys.bind("find_close", self.search, self.hide_search, Qt.WindowShortcut)
        if Path(path).suffix.lower() in {".md", ".markdown"}:
            self.mode = QPushButton("Preview", self)
            self.mode.clicked.connect(self.toggle_preview)
            self.toolbar.addWidget(self.mode)
        self.toolbar.addStretch()
        self.reload()

    def reload(self):
        path = self.path
        self.start_load(lambda cancelled: read_text_preview(path, cancelled))

    def loaded(self, result):
        if not super().loaded(result):
            return
        self._text, self._partial = result["text"], result["partial"]
        if self.highlighter is not None:
            self.highlighter.setDocument(None)
            self.highlighter.deleteLater()
            self.highlighter = None
        self.source.setPlainText(self._text)
        self.source.document().setModified(False)
        lexer = lexer_for_path(self.path)
        if lexer is not None:
            self.highlighter = PygmentsHighlighter(self.source.document(), lexer)
        self.stack.setCurrentWidget(self.source)
        if hasattr(self, "mode"):
            self.mode.setText("Preview")
            self.mode.setEnabled(len(self._text.encode("utf-8")) <= MARKDOWN_PREVIEW_LIMIT)
            self.mode.setToolTip("Preview is limited to 128 KiB of loaded Markdown")
        detail = f"Partial view · {result['reason']} · Search and copy cover loaded text only"
        self._load_notice = detail if self._partial else f"Read-only · {result['encoding']}"
        self.status.setText(self._load_notice)
        self._external_change()

    def show_search(self):
        self.stack.setCurrentWidget(self.source)
        if hasattr(self, "mode"):
            self.mode.setText("Preview")
        self.search.show()
        self.search.setFocus()
        self.search.selectAll()

    def hide_search(self):
        self.search.hide()
        self.source.setFocus()

    def find_next(self):
        query = self.search.text()
        if not query:
            return
        if not self.source.find(query):
            cursor = self.source.textCursor()
            cursor.movePosition(QTextCursor.Start)
            self.source.setTextCursor(cursor)
            found = self.source.find(query)
        else:
            found = True
        self.search.setToolTip("" if found else "No match in loaded text")

    def toggle_preview(self):
        if self.stack.currentWidget() is not self.source:
            self.stack.setCurrentWidget(self.source)
            self.mode.setText("Preview")
            return
        if self.preview is None:
            from .response import ResponseView
            self.preview = ResponseView(self)
            self.preview.document_view.setOpenExternalLinks(False)
            self.preview.document_view.setOpenLinks(False)
            self.preview.document_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.preview.document_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.stack.addWidget(self.preview)
        self.preview.finish(self._text)
        self.stack.setCurrentWidget(self.preview)
        self.mode.setText("Source")

    def context_snapshot(self):
        first = self.source.firstVisibleBlock()
        last = self.source.cursorForPosition(self.source.viewport().rect().bottomRight())
        return {"path": self.path, "selected_text": self.source.textCursor().selectedText(),
                "visible_lines": (first.blockNumber() + 1, last.blockNumber() + 1),
                "partial": self._partial}

    def dispose(self):
        super().dispose()
        if self.highlighter is not None:
            self.highlighter.setDocument(None)


def default_viewer_registry():
    from .pdf_viewer import PdfViewer
    registry = ViewerRegistry()
    registry.register(PdfViewer)
    registry.register(TextViewer)
    return registry
