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
"""Workspace-local Qt PDF rendering with document preparation off the GUI thread."""
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QSpinBox
from shiboken6 import delete

from .file_viewer import FileViewer, file_snapshot

try:
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPdfWidgets import QPdfView
except ImportError:
    QPdfDocument = QPdfView = None

PDF_BYTE_LIMIT = 128 * 1024 * 1024
PDF_PAGE_LIMIT = 10000


def load_pdf(path, gui_thread, cancelled):
    snapshot = file_snapshot(path)
    if snapshot[0] > PDF_BYTE_LIMIT:
        raise ValueError("PDF is too large to view (128 MiB limit)")
    if cancelled.is_set():
        return None
    document = QPdfDocument()
    try:
        error = document.load(path)
        if error != QPdfDocument.Error.None_ or document.status() != QPdfDocument.Status.Ready:
            raise ValueError("PDF could not be loaded · Invalid, encrypted or unreadable document")
        if document.pageCount() > PDF_PAGE_LIMIT:
            raise ValueError("PDF has too many pages to view (10,000 page limit)")
        if file_snapshot(path) != snapshot:
            raise ValueError("File changed while loading; reload to try again")
        if cancelled.is_set():
            delete(document)
            return None
        document.moveToThread(gui_thread)
        return {"document": document, "snapshot": snapshot}
    except Exception:
        delete(document)
        raise


class PdfViewer(FileViewer):
    @staticmethod
    def supports(path):
        return Path(path).suffix.lower() == ".pdf"

    def __init__(self, path):
        super().__init__(path)
        self.document = None
        if QPdfView is None:
            self.status.setText("PDF viewing requires the Qt PDF modules from PySide6 Addons")
            self.reload_button.setEnabled(False)
            return
        self.view = QPdfView(self)
        self.view.setMinimumSize(0, 0)
        self.view.setPageMode(QPdfView.PageMode.MultiPage)
        self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.reload_button.setText("↻")
        self.reload_button.setAccessibleName("Reload file")
        self.reload_button.setFixedWidth(32)
        self.page = QSpinBox(self)
        self.page.setRange(1, 1)
        self.page.setToolTip("Go to page")
        self.page.setAccessibleName("Current PDF page")
        self.page.setMinimumWidth(0)
        self.page.valueChanged.connect(self.go_to_page)
        self.toolbar.addWidget(self.page)
        self.toolbar.addStretch()
        zoom_controls = QHBoxLayout()
        zoom_controls.setSpacing(4)
        for text, tooltip, callback in (
                ("−", "Zoom out", lambda: self.zoom(1 / 1.2)),
                ("+", "Zoom in", lambda: self.zoom(1.2)),
                ("Fit", "Fit page width", self.fit_width)):
            button = QPushButton(text, self)
            button.setToolTip(tooltip)
            button.setFixedWidth(32)
            button.clicked.connect(callback)
            button.setAccessibleName(tooltip)
            zoom_controls.addWidget(button)
        zoom_controls.addStretch()
        self.layout_box.insertLayout(1, zoom_controls)
        self.layout_box.addWidget(self.view, 1)
        self.view.pageNavigator().currentPageChanged.connect(self.page_changed)
        self.reload()

    def reload(self):
        if QPdfDocument is None:
            return
        path, thread = self.path, QApplication.instance().thread()
        self.start_load(lambda cancelled: load_pdf(path, thread, cancelled))

    def loaded(self, result):
        if not super().loaded(result):
            return
        previous = self.document
        self.document = result["document"]
        self.document.setParent(self)
        self.view.setDocument(self.document)
        if previous is not None:
            previous.close()
            previous.deleteLater()
        self.page.setRange(1, max(1, self.document.pageCount()))
        self.page.setSuffix(f" / {self.document.pageCount()}")
        self.page_changed(0)
        self._load_notice = f"Read-only · {self.document.pageCount()} pages"
        self.status.setText(self._load_notice)
        self._external_change()

    def go_to_page(self, page):
        if self.document is not None:
            self.view.pageNavigator().jump(page - 1, QPointF())

    def page_changed(self, page):
        self.page.blockSignals(True)
        self.page.setValue(page + 1)
        self.page.blockSignals(False)

    def zoom(self, factor):
        self.view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.view.setZoomFactor(max(0.1, min(8.0, self.view.zoomFactor() * factor)))

    def fit_width(self):
        self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)

    def context_snapshot(self):
        return {"path": self.path,
                "page": self.view.pageNavigator().currentPage() + 1
                if QPdfView is not None else None}

    def dispose(self):
        super().dispose()
        if self.document is not None:
            self.view.setDocument(None)
            self.document.close()
            self.document.deleteLater()
            self.document = None
