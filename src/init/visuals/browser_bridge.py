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
"""Thread-safe navigation requests for Arlo's embedded browser."""

import threading
from dataclasses import dataclass, field
from urllib.parse import urlparse

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication


@dataclass(eq=False)
class BrowserRequest:
    url: str
    completed: threading.Event = field(default_factory=threading.Event)
    error: str | None = None


_registry_lock = threading.Lock()
_bridge = None


class BrowserBridge(QObject):
    requested = Signal(object)

    def __init__(self, parent):
        global _bridge
        app = QApplication.instance()
        if app is None or QThread.currentThread() != app.thread():
            raise RuntimeError("BrowserBridge requires the GUI thread")
        super().__init__(parent)
        self._lock = threading.Lock()
        self._pending = set()
        self._closed = False
        self.requested.connect(self._open, Qt.QueuedConnection)
        app.aboutToQuit.connect(self.shutdown)
        self.destroyed.connect(lambda: self.shutdown())
        with _registry_lock:
            _bridge = self

    def request(self, url, timeout=15):
        request = BrowserRequest(url)
        with self._lock:
            if self._closed:
                raise RuntimeError("Arlo's embedded browser is unavailable")
            self._pending.add(request)
        try:
            if QThread.currentThread() == self.thread():
                self._open(request)
            else:
                self.requested.emit(request)
            if not request.completed.wait(timeout):
                with self._lock:
                    if not request.completed.is_set():
                        self._finish(request, "Browser request timed out and was cancelled")
        except Exception as error:
            with self._lock:
                self._finish(request, str(error))
        if request.error:
            raise RuntimeError(request.error)

    def _finish(self, request, error=None):
        if request.completed.is_set():
            return
        request.error = error
        self._pending.discard(request)
        request.completed.set()

    @Slot(object)
    def _open(self, request):
        with self._lock:
            if self._closed or request.completed.is_set():
                return
            view = None
            try:
                from .browser import BrowserView
                workspace = self.parent().workspace
                panel = workspace.get_panel(workspace.active_panel_id)
                if panel is None or not isinstance(panel.content, BrowserView):
                    panel = next((workspace.get_panel(pid) for pid in workspace.panel_ids
                                  if isinstance(workspace.get_panel(pid).content, BrowserView)
                                  and pid not in workspace._closing_panels), None)
                if panel is not None and panel.panel_id in workspace._closing_panels:
                    panel = None
                if panel is None:
                    view = BrowserView(initial_url=None)
                    if view.web_view is None:
                        raise RuntimeError("Arlo's embedded browser requires Qt WebEngine")
                    view.setProperty("workspaceViewKey", "browser")
                    panel_id = workspace.open_panel(title="Browser", content=view)
                else:
                    view = panel.content
                    panel_id = panel.panel_id
                    if view.web_view is None:
                        raise RuntimeError("Arlo's embedded browser requires Qt WebEngine")
                view.open_url(request.url)
                workspace.focus_panel(panel_id)
                window = self.parent()
                if (not window.isVisible() or window.isMinimized()):
                    restore = getattr(window, "restore_from_mascot", None)
                    if restore is not None:
                        restore()
                self._finish(request)
            except Exception as error:
                if view is not None and view.parentWidget() is None:
                    view.deleteLater()
                self._finish(request, str(error))

    @Slot()
    def shutdown(self):
        global _bridge
        with _registry_lock:
            if _bridge is self:
                _bridge = None
        with self._lock:
            self._closed = True
            for request in tuple(self._pending):
                self._finish(request, "Arlo's embedded browser was closed")


def open_embedded_url(url: str) -> None:
    """Navigate on the GUI thread, or raise without launching an external browser."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("A valid HTTP or HTTPS URL is required")
    with _registry_lock:
        bridge = _bridge
    if bridge is None:
        raise RuntimeError("The embedded browser requires the running Arlo desktop")
    bridge.request(url)
