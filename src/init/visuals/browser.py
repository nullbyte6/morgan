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

    def __init__(self, parent=None, *, initial_url="https://google.com"):
        super().__init__(parent)
        self.setObjectName("browserView")
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 6)
        toolbar.setSpacing(8)
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
        self.address_bar.setMinimumWidth(80)
        self.address_bar.setMinimumHeight(40)
        self.address_bar.setAccessibleName("Web address or search")
        self.address_bar.returnPressed.connect(self.navigate)
        for button, label in ((self.back_button, "Back"),
                              (self.forward_button, "Forward"),
                              (self.reload_button, "Reload")):
            button.setFixedSize(40, 40)
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(label)
            button.setAccessibleName(label)
            toolbar.addWidget(button)
        self.back_button.setEnabled(False)
        self.forward_button.setEnabled(False)
        toolbar.addWidget(self.address_bar, 1)
        self.extensions_button = QPushButton("…", self)
        self.extensions_button.setObjectName("browserExtensions")
        self.extensions_button.setFixedSize(40, 40)
        self.extensions_button.setToolTip("Extensions")
        self.extensions_button.setAccessibleName("Extensions")
        self.extensions_button.setCursor(Qt.PointingHandCursor)
        self.extensions_button.setEnabled(False)
        self.extensions_button.clicked.connect(self._show_extensions)
        toolbar.addWidget(self.extensions_button)
        self.status = QLabel("Ready", self)
        self.status.setObjectName("browserStatus")
        self.status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        root.addLayout(toolbar)
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
        except ImportError:
            self.web_view = None
            message = QLabel("Embedded browser unavailable. Install PySide6-WebEngine.", self)
            message.setObjectName("browserUnavailable")
            message.setAlignment(Qt.AlignCenter)
            message.setWordWrap(True)
            root.addWidget(message, 1)
            root.addWidget(self.status)
            self.address_bar.setEnabled(False)
            self.reload_button.setEnabled(False)
            self.status.setText("Browser unavailable")
            return
        self.web_view = QWebEngineView(self)
        from .browser_session import get_browser_session
        self.session = get_browser_session()
        self.web_view.setPage(self.session.create_page(self.web_view))
        self.extensions_button.setEnabled(self.session.extensions is not None)
        if self.session.extensions is None:
            self.extensions_button.setToolTip("Extensions require Qt WebEngine 6.10 or newer")
        self.web_view.setObjectName("browserWebView")
        self.web_view.urlChanged.connect(self._on_url_changed)
        self.web_view.loadStarted.connect(lambda: self.status.setText("Loading…"))
        self.web_view.loadFinished.connect(self._on_load_finished)
        root.addWidget(self.web_view, 1)
        root.addWidget(self.status)
        self.web_view.page().newWindowRequested.connect(self._open_new_window)
        if initial_url:
            self.navigate(initial_url)

    def _show_extensions(self):
        from .browser_extensions import ExtensionsView
        from .workspace import Workspace, WorkspacePanel
        workspace = self.parentWidget()
        target_id = None
        while workspace is not None and not isinstance(workspace, Workspace):
            if isinstance(workspace, WorkspacePanel):
                target_id = workspace.panel_id
            workspace = workspace.parentWidget()
        if workspace is None:
            self.status.setText("Open the browser in an Arlo workspace to manage extensions")
            return
        for panel_id in workspace.panel_ids:
            panel = workspace.get_panel(panel_id)
            if (panel.property("workspaceViewKey") == "browser_extensions"
                    and panel_id not in workspace._closing_panels):
                workspace.focus_panel(panel_id)
                return
        workspace.open_panel(title="Extensions",
                             content=ExtensionsView(self.session, workspace),
                             target_id=target_id)

    def _open_new_window(self, request):
        """Keep links requesting a new window inside this browser panel."""
        url = request.requestedUrl()
        if url.scheme() not in ("http", "https") and url.toString() != "chrome://qt":
            self.web_view.setUrl(url)

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
        """Open a URL requested by the workspace or assistant tools."""
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
        self._update_navigation()

    def _update_navigation(self):
        history = self.web_view.history()
        self.back_button.setEnabled(history.canGoBack())
        self.forward_button.setEnabled(history.canGoForward())

    def _on_load_finished(self, ok):
        self.status.setText("Ready" if ok else "Could not load page")
        self._update_navigation()
