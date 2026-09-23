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
"""Small embedded browser view used by the Arlo workspace."""

from PySide6.QtCore import QUrl, Qt, Slot
from PySide6.QtWidgets import *

class BrowserView(QWidget):
    """A small http(s) browser for workspace panels."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("browserView")
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 6)
        toolbar.setSpacing(6)
        self.back_button = QPushButton("‹", self)
        self.back_button.setObjectName("browserBack")
        self.back_button.clicked.connect(self._go_back)
        self.forward_button = QPushButton("›", self)
        self.forward_button.setObjectName("browserForward")
        self.forward_button.clicked.connect(self._go_forward)
        self.reload_button = QPushButton("↻", self)
        self.reload_button.setObjectName("browserReload")
        self.reload_button.clicked.connect(self._reload)
        self.address_bar = QLineEdit(self)
        self.address_bar.setObjectName("browserAddressBar")
        self.address_bar.setPlaceholderText("Enter a URL or search the web")
        self.address_bar.setClearButtonEnabled(True)
        self.address_bar.returnPressed.connect(self.navigate)
        for button in (self.back_button, self.forward_button, self.reload_button):
            toolbar.addWidget(button)
        toolbar.addWidget(self.address_bar, 1)
        self.status = QLabel("Ready", self)
        self.status.setObjectName("browserStatus")
        self.status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.addLayout(toolbar)
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
        except ImportError:
            self.web_view = None
            message = QLabel("Embedded browser unavailable. Install PySide6-WebEngine.", self)
            message.setObjectName("browserUnavailable")
            message.setAlignment(Qt.AlignCenter)
            root.addWidget(message, 1)
            root.addWidget(self.status)
            self.address_bar.setEnabled(False)
            return
        self.web_view = QWebEngineView(self)
        self.web_view.setObjectName("browserWebView")
        self.web_view.urlChanged.connect(self._on_url_changed)
        self.web_view.loadStarted.connect(lambda: self.status.setText("Loading…"))
        self.web_view.loadFinished.connect(self._on_load_finished)
        root.addWidget(self.web_view, 1)
        root.addWidget(self.status)
        self.navigate("https://google.com")

    @Slot()
    def navigate(self, text=None):
        if self.web_view is None:
            return
        text = self.address_bar.text().strip() if text is None else text.strip()
        if not text:
            return
        if " " in text:
            encoded = QUrl.toPercentEncoding(text).data().decode()
            url = QUrl("https://duckduckgo.com/?q=" + encoded)
        else:
            url = QUrl.fromUserInput(text)
        if url.scheme() not in ("http", "https"):
            self.status.setText("Only http and https URLs are supported")
            return
        self.web_view.setUrl(url)

    def open_url(self, url: str):
        """Open an URL from the workspace or a future Arlo bridge."""
        self.address_bar.setText(url)
        self.navigate(url)

    def _go_back(self):
        if self.web_view is not None:
            self.web_view.back()

    def _go_forward(self):
        if self.web_view is not None:
            self.web_view.forward()

    def _reload(self):
        if self.web_view is not None:
            self.web_view.reload()

    def _on_url_changed(self, url):
        self.address_bar.setText(url.toString())

    def _on_load_finished(self, ok):
        self.status.setText("Ready" if ok else "Could not load page")
