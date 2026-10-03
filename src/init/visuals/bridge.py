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
"""Request/result handoff from assistant tools to the existing Qt application."""

from src.init.identity import get_assistant_name

import threading
import uuid
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication

from src.init.visuals.gateway import failure as _failure
from src.init.visuals.gateway import get_bridge, register_bridge, release_bridge
from src.init.visuals.schema import Flowchart


@dataclass
class FlowchartRequest:
    """One validated request whose outcome is protected by the bridge lock."""
    chart: Flowchart
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    completed: threading.Event = field(default_factory=threading.Event)
    result: dict | None = None


class FlowchartBridge(QObject):
    """Own diagram workspace panels and render them on the GUI thread."""
    requested = Signal(object)

    def __init__(self, parent=None):
        app = QApplication.instance()
        if not isinstance(app, QApplication) or QThread.currentThread() != app.thread():
            raise RuntimeError("The flowchart bridge must be created on the QApplication GUI thread")
        if get_bridge("flowchart") is not None:
            raise RuntimeError("A flowchart bridge is already registered")
        super().__init__(parent)
        self._lock = threading.Lock()
        self._closed = False
        self._pending = {}
        self.windows = {}
        self._panel_requests = {}
        self._workspace_connected = False
        self._workspace = None
        self.requested.connect(self._render, Qt.QueuedConnection)
        app.aboutToQuit.connect(self.shutdown)
        self.destroyed.connect(lambda: self._release())
        register_bridge("flowchart", self)

    def request(self, chart, *, timeout=15.0):
        """Submit from any thread and return only a confirmed render outcome."""
        request = FlowchartRequest(chart)
        with self._lock:
            if self._closed:
                return _failure("unavailable", "The flowchart desktop bridge is closed")
            self._pending[request.id] = request
        try:
            if QThread.currentThread() == self.thread():
                self._render(request)
            else:
                self.requested.emit(request)
        except Exception as error:
            with self._lock:
                self._complete(request, _failure("bridge_error", str(error)))
        if not request.completed.wait(timeout):
            with self._lock:
                self._complete(request, _failure("timeout", "Flowchart rendering timed out; "
                                                            "the request was cancelled"))
        return request.result

    def _complete(self, request, result):
        """Resolve a request exactly once while holding the bridge lock."""
        if request.result is None:
            request.result = result
            self._pending.pop(request.id, None)
            request.completed.set()

    @Slot(object)
    def _render(self, request):
        app = QApplication.instance()
        if app is None or QThread.currentThread() != app.thread():
            with self._lock:
                self._complete(request, _failure("wrong_thread", "Rendering requires the GUI thread"))
            return
        with self._lock:
            if self._closed or request.completed.is_set():
                return
        widget = None
        try:
            from .window import FlowchartWidget
            window = self.parent()
            workspace = getattr(window, "workspace", None)
            if workspace is None:
                raise RuntimeError(f"The flowchart bridge requires the {get_assistant_name()} workspace")
            self._workspace = workspace
            if not self._workspace_connected:
                workspace.panel_closed.connect(self._on_panel_closed)
                self._workspace_connected = True
            widget = FlowchartWidget(request.chart)

            panel_id = workspace.open_panel(
                title=request.chart.title,
                content=widget,
                target_id=window.main_workspace_panel_id,
                direction=Qt.Key_Right)

            self._panel_requests[panel_id] = request.id
            widget.destroyed.connect(
                lambda: self.windows.pop(request.id, None))
            with self._lock:
                if self._closed or request.completed.is_set():
                    workspace.close_panel(panel_id)
                    return
                self.windows[request.id] = widget
                self._complete(request, {"ok": True, "window_id": request.id,
                                        "panel_id": panel_id,
                                        "title": request.chart.title,
                                        "nodes": len(request.chart.nodes),
                                        "edges": len(request.chart.edges), "status": "opened"})
        except Exception as error:
            if widget is not None:
                self.windows.pop(request.id, None)
                widget.deleteLater()
            with self._lock:
                self._complete(request, _failure("render_error", f"Could not render flowchart: {error}"))

    @Slot(str)
    def _on_panel_closed(self, panel_id: str) -> None:
        """Forget flowchart state after its workspace panel is closed."""
        request_id = self._panel_requests.pop(panel_id, None)
        if request_id is not None:
            self.windows.pop(request_id, None)

    @Slot()
    def shutdown(self):
        """Cancel pending requests and close owned windows on desktop shutdown."""
        app = QApplication.instance()
        if app is not None and QThread.currentThread() != app.thread():
            raise RuntimeError("Flowchart shutdown requires the GUI thread")
        self._release()

    def _release(self):
        """Release Python state even when Qt destroys the bridge's owner."""
        release_bridge("flowchart", self)
        with self._lock:
            self._closed = True
            for request in list(self._pending.values()):
                self._complete(request, _failure("unavailable", "The flowchart desktop bridge was closed"))
        workspace = self._workspace
        if workspace is not None:
            for panel_id in list(self._panel_requests):
                workspace.close_panel(panel_id)
        self._panel_requests.clear()
        self.windows.clear()
