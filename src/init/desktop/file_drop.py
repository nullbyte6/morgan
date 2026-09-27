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
"""One desktop file-drop policy for composer attachments and empty
workspaces."""
from pathlib import Path
import weakref

from PySide6.QtCore import QDir, QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout, QWidget
from shiboken6 import isValid

from ..visuals.file_viewer import default_viewer_registry
from ..visuals.workspace import WorkspacePanel


def local_file_paths(mime):
    if not mime.hasUrls():
        return ()
    urls = mime.urls()
    if not urls:
        return ()
    paths = []
    for url in urls:
        path = url.toLocalFile()
        if (not url.isLocalFile() or url.host().lower() not in {"", "localhost"}
                or not path or not QDir.isAbsolutePath(path)
                or path.startswith(("\\\\", "//"))):
            return ()
        paths.append(path)
    return tuple(paths)


class FileDropRouter(QObject):
    """A single event filter routes in widget-local coordinates, including ZoomView."""

    def __init__(self, workspace, composer, attachments, parent=None, registry=None):
        super().__init__(parent)
        self.workspace = workspace
        self.composers = {composer: attachments}
        self.registry = registry or default_viewer_registry()
        self._indicator = None
        self._indicator_target = None
        self._expiry = QTimer(self)
        self._expiry.setSingleShot(True)
        self._expiry.timeout.connect(self.clear_indicator)
        self._enable_drops(composer)
        for panel_id in workspace.panel_ids:
            self._enable_drops(workspace.get_panel(panel_id))
        workspace.panel_opened.connect(self._panel_opened)
        workspace.panel_closed.connect(self.clear_indicator)
        QApplication.instance().installEventFilter(self)

    def register_composer(self, composer, attachments):
        self.composers[composer] = attachments
        self._enable_drops(composer)
        composer.destroyed.connect(lambda: self.composers.pop(composer, None))

    def _panel_opened(self, panel_id):
        self._enable_drops(self.workspace.get_panel(panel_id))

    def _enable_drops(self, widget):
        if widget is None:
            return
        widget.setAcceptDrops(True)
        for child in widget.findChildren(QWidget):
            child.setAcceptDrops(True)

    def target_for(self, widget):
        current = widget
        while current is not None:
            if current in self.composers:
                return current
            if isinstance(current, WorkspacePanel):
                return current
            current = current.parentWidget()
        return None

    def decision(self, target, paths):
        if not paths:
            return "", "Only local files can be dropped here"
        if target in self.composers:
            if not self.composers[target].isEnabled():
                return "", "Attachments are unavailable while a message is being sent"
            return "attachment", "Drop to attach files"
        if not self.workspace.can_open_file(target):
            return "", "Open files in an empty workspace"
        if len(paths) != 1:
            return "", "Drop one file to open a read-only view"
        if not self.registry.supports(paths[0]):
            return "", "Unsupported file type"
        return "viewer", "Drop to open a read-only file view"

    def show_indicator(self, target, message, valid):
        owner = target.content_host if isinstance(target, WorkspacePanel) else target
        if self._indicator_target is None or self._indicator_target() is not owner:
            self.clear_indicator()
            self._indicator_target = weakref.ref(owner)
            self._indicator = QFrame(owner)
            self._indicator.setObjectName("desktopFileDropIndicator")
            self._indicator.setAttribute(Qt.WA_TransparentForMouseEvents)
            layout = QVBoxLayout(self._indicator)
            self._message = QLabel(self._indicator)
            self._message.setTextFormat(Qt.PlainText)
            self._message.setWordWrap(True)
            self._message.setAlignment(Qt.AlignCenter)
            layout.addWidget(self._message)
        self._indicator.setProperty("valid", valid)
        self._indicator.style().unpolish(self._indicator)
        self._indicator.style().polish(self._indicator)
        self._message.setText(message)
        self._indicator.setGeometry(owner.rect())
        self._indicator.show()
        self._indicator.raise_()
        if valid:
            self._expiry.stop()
        else:
            self._expiry.start(1500)

    def clear_indicator(self, *_):
        self._expiry.stop()
        if self._indicator is not None and isValid(self._indicator):
            self._indicator.hide()
            self._indicator.deleteLater()
        self._indicator = None
        self._indicator_target = None

    def eventFilter(self, watched, event):
        if not isinstance(watched, QWidget):
            return False
        kind = event.type()
        if kind == QEvent.ChildPolished:
            child = event.child()
            if isinstance(child, QWidget) and self.target_for(watched) is not None:
                self._enable_drops(child)
            return False
        if kind == QEvent.Resize:
            owner = self._indicator_target() if self._indicator_target else None
            if watched is owner and self._indicator is not None and isValid(self._indicator):
                self._indicator.setGeometry(watched.rect())
            return False
        if kind not in {QEvent.DragEnter, QEvent.DragMove, QEvent.DragLeave, QEvent.Drop}:
            return False
        target = self.target_for(watched)
        if target is None:
            return False
        if kind == QEvent.DragLeave:
            self.clear_indicator()
            return False
        mime = event.mimeData()
        if mime.hasFormat(WorkspacePanel.MIME_TYPE):
            return False
        if not mime.hasUrls():
            event.ignore()
            return True
        paths = local_file_paths(mime)
        action, message = self.decision(target, paths)
        if kind in {QEvent.DragEnter, QEvent.DragMove}:
            self.show_indicator(target, message, bool(action))
            if action:
                event.setDropAction(Qt.CopyAction)
                event.accept()
            else:
                event.ignore()
            return True
        self.clear_indicator()
        if not action:
            self.show_indicator(target, message, False)
            event.ignore()
            return True
        try:
            if action == "attachment":
                if not self.composers[target].add_files(paths, interactive=False):
                    self.show_indicator(target, "Attachment count limit reached", False)
            else:
                content = self.registry.create(paths[0])
                target.set_content(content)
                target.set_title(Path(paths[0]).name)
                target.title_label.setToolTip(paths[0])
                self.workspace.focus_panel(target.panel_id)
        except (OSError, ValueError, RuntimeError) as error:
            self.show_indicator(target, str(error) or "Unable to open file", False)
            event.ignore()
            return True
        event.setDropAction(Qt.CopyAction)
        event.accept()
        return True
