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

"""Embedded tiling workspace for Arlo's desktop interface."""
from __future__ import annotations

import sys
import uuid

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import *

class WorkspacePanel(QFrame):
    """An independently closable container for embedded content."""

    close_requested = Signal(str)
    focus_requested = Signal(str)

    def __init__(
        self,
        panel_id: str,
        title: str,
        content: QWidget | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)

        self.panel_id = panel_id
        self.title = title

        self.setObjectName("workspacePanel")
        self.setProperty("workspacePanel", True)
        self.setFrameShape(QFrame.NoFrame)
        self.setMinimumSize(180, 140)
        self.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Expanding,
        )

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self.header = QWidget(self)
        self.header.setObjectName("workspacePanelHeader")
        self.header.setFixedHeight(38)

        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(12, 0, 6, 0)
        header_layout.setSpacing(8)

        self.title_label = QLabel(title, self.header)
        self.title_label.setObjectName("workspacePanelTitle")
        self.title_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse
        )

        self.close_button = QPushButton("×", self.header)
        self.close_button.setObjectName("workspacePanelClose")
        self.close_button.setFixedSize(28, 28)
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.setToolTip("Close panel")

        header_layout.addWidget(self.title_label, 1)
        header_layout.addWidget(self.close_button)

        self._layout.addWidget(self.header)

        self.content_host = QWidget(self)
        self.content_host.setObjectName("workspacePanelContent")

        self.content_layout = QVBoxLayout(self.content_host)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)

        self._layout.addWidget(self.content_host, 1)

        self.content: QWidget | None = None

        if content is None:
            content = self._create_placeholder()

        self.set_content(content)

        self.close_button.clicked.connect(
            lambda: self.close_requested.emit(self.panel_id)
        )

    def _create_placeholder(self) -> QWidget:
        """Create an empty visual surface for the initial milestone."""

        placeholder = QWidget()
        placeholder.setObjectName("workspacePlaceholder")

        layout = QVBoxLayout(placeholder)
        layout.setContentsMargins(16, 16, 16, 16)

        label = QLabel("Empty workspace", placeholder)
        label.setObjectName("workspacePlaceholderLabel")
        label.setAlignment(Qt.AlignCenter)

        layout.addWidget(label)

        return placeholder

    def set_content(self, content: QWidget) -> None:
        """Replace the embedded widget without creating a top-level window."""

        if self.content is content:
            return

        if self.content is not None:
            previous = self.content
            self.content_layout.removeWidget(previous)
            previous.setParent(None)
            previous.deleteLater()

        self.content = content
        self.content_layout.addWidget(content)

    def set_title(self, title: str) -> None:
        """Update the visible panel title."""

        self.title = title
        self.title_label.setText(title)

    def mousePressEvent(self, event):
        self.focus_requested.emit(self.panel_id)
        super().mousePressEvent(event)


class WorkspaceSplitter(QSplitter):
    """A movable split in the workspace layout tree."""

    def __init__(
        self,
        orientation: Qt.Orientation,
        parent: QWidget | None = None,
    ):
        super().__init__(orientation, parent)

        self.setObjectName("workspaceSplitter")
        self.setChildrenCollapsible(False)
        self.setHandleWidth(8)
        self.setOpaqueResize(True)

        self.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Expanding,
        )


class Workspace(QWidget):
    """Manage automatically tiled panels inside one existing Qt window."""

    panel_opened = Signal(str)
    panel_closed = Signal(str)
    panel_focused = Signal(str)
    layout_changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self.setObjectName("arloWorkspace")

        self._panels: dict[str, WorkspacePanel] = {}
        self._active_panel_id: str | None = None
        self._root: QWidget | None = None
        self._next_orientation = Qt.Horizontal

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Expanding,
        )

    @property
    def panel_count(self) -> int:
        return len(self._panels)

    @property
    def active_panel_id(self) -> str | None:
        return self._active_panel_id

    @property
    def panel_ids(self) -> tuple[str, ...]:
        return tuple(self._panels)

    def get_panel(self, panel_id: str) -> WorkspacePanel | None:
        """Return a registered panel by its stable identifier."""

        return self._panels.get(panel_id)

    def open_panel(
        self,
        title: str = "Workspace",
        content: QWidget | None = None,
        *,
        panel_id: str | None = None,
        target_id: str | None = None,
        orientation: Qt.Orientation | None = None,
    ) -> str:
        """Insert a new panel by splitting an existing workspace leaf."""

        panel_id = panel_id or uuid.uuid4().hex

        if panel_id in self._panels:
            raise ValueError(f"Panel already exists: {panel_id}")

        if content is not None and content.isWindow():
            raise ValueError(
                "Workspace content must be an embedded QWidget, "
                "not a top-level window"
            )

        if target_id is not None and target_id not in self._panels:
            raise ValueError(f"Unknown target panel: {target_id}")

        panel = WorkspacePanel(
            panel_id=panel_id,
            title=title,
            content=content,
        )

        panel.close_requested.connect(self.close_panel)
        panel.focus_requested.connect(self.focus_panel)

        if self._root is None:
            self._root = panel
            self._layout.addWidget(panel)

        else:
            target = self._select_target(target_id)

            if orientation is None:
                orientation = self._next_orientation

            self._insert_panel(target, panel, orientation)

            self._next_orientation = (
                Qt.Vertical
                if orientation == Qt.Horizontal
                else Qt.Horizontal
            )

        self._panels[panel_id] = panel

        self.focus_panel(panel_id)

        self.panel_opened.emit(panel_id)
        self.layout_changed.emit()

        return panel_id

    def _select_target(
        self,
        target_id: str | None,
    ) -> WorkspacePanel:
        """Choose the leaf that receives the next split."""

        if target_id is not None:
            return self._panels[target_id]

        if self._active_panel_id in self._panels:
            return self._panels[self._active_panel_id]

        return next(iter(self._panels.values()))

    def _insert_panel(
        self,
        target: WorkspacePanel,
        panel: WorkspacePanel,
        orientation: Qt.Orientation,
    ) -> None:
        """Replace a leaf with a splitter containing the old and new leaves."""

        parent = target.parentWidget()

        if isinstance(parent, QSplitter):
            index = parent.indexOf(target)
            original_sizes = parent.sizes()

            target.setParent(None)

            split = WorkspaceSplitter(orientation)
            split.addWidget(target)
            split.addWidget(panel)
            split.setSizes([1, 1])

            parent.insertWidget(index, split)

            if len(original_sizes) == parent.count():
                parent.setSizes(original_sizes)

        else:
            self._layout.removeWidget(target)
            target.setParent(None)

            split = WorkspaceSplitter(orientation)
            split.addWidget(target)
            split.addWidget(panel)

            self._root = split
            self._layout.addWidget(split)

            split.setSizes([1, 1])

        split.splitterMoved.connect(self._on_splitter_moved)

    def close_panel(self, panel_id: str) -> bool:
        """Remove a leaf and promote its surviving sibling."""

        panel = self._panels.get(panel_id)

        if panel is None:
            return False

        parent = panel.parentWidget()

        if isinstance(parent, QSplitter):
            grandparent = parent.parentWidget()
            siblings = [
                parent.widget(index)
                for index in range(parent.count())
                if parent.widget(index) is not panel
            ]

            if len(siblings) != 1:
                raise RuntimeError(
                    "Workspace split must contain exactly two children"
                )

            sibling = siblings[0]

            if isinstance(grandparent, QSplitter):
                index = grandparent.indexOf(parent)
                original_sizes = grandparent.sizes()

                sibling.setParent(None)
                panel.setParent(None)

                parent.setParent(None)
                grandparent.insertWidget(index, sibling)

                if len(original_sizes) == grandparent.count():
                    grandparent.setSizes(original_sizes)

                parent.deleteLater()

            else:
                sibling.setParent(None)
                panel.setParent(None)

                self._layout.removeWidget(parent)
                parent.setParent(None)
                parent.deleteLater()

                self._root = sibling
                self._layout.addWidget(sibling)

        else:
            self._layout.removeWidget(panel)
            panel.setParent(None)
            self._root = None

        del self._panels[panel_id]

        panel.deleteLater()

        if self._active_panel_id == panel_id:
            self._active_panel_id = None

            if self._panels:
                self.focus_panel(next(reversed(self._panels)))

        self.panel_closed.emit(panel_id)
        self.layout_changed.emit()

        return True

    def focus_panel(self, panel_id: str) -> bool:
        """Mark one panel as active without changing its camera or content."""

        if panel_id not in self._panels:
            return False

        if self._active_panel_id == panel_id:
            return True

        previous = self._panels.get(self._active_panel_id)

        if previous is not None:
            previous.setProperty("active", False)
            previous.style().unpolish(previous)
            previous.style().polish(previous)

        self._active_panel_id = panel_id

        panel = self._panels[panel_id]
        panel.setProperty("active", True)

        panel.style().unpolish(panel)
        panel.style().polish(panel)

        self.panel_focused.emit(panel_id)

        return True

    def replace_content(
        self,
        panel_id: str,
        content: QWidget,
    ) -> bool:
        """Replace one panel's content without affecting neighboring panels."""

        panel = self._panels.get(panel_id)

        if panel is None:
            return False

        if content.isWindow():
            raise ValueError(
                "Workspace content must be an embedded QWidget"
            )

        panel.set_content(content)

        return True

    def close_all(self) -> None:
        """Close every registered panel."""

        for panel_id in tuple(self._panels):
            self.close_panel(panel_id)

    def _on_splitter_moved(self, position: int, index: int) -> None:
        self.layout_changed.emit()


WORKSPACE_STYLESHEET = """
#arloWorkspace {
    background: #24273a;
}

#workspacePanel {
    background: #363a4f;
    border: 1px solid #494d64;
    border-radius: 12px;
}

#workspacePanel[active="true"] {
    border: 1px solid #b7bdf8;
}

#workspacePanelHeader {
    background: transparent;
    border: none;
}

#workspacePanelTitle {
    color: #cad3f5;
    font-size: 12px;
    font-weight: 600;
    border: none;
}

#workspacePanelClose {
    color: #a5adcb;
    background: transparent;
    border: none;
    border-radius: 6px;
    font-size: 19px;
}

#workspacePanelClose:hover {
    color: #ed8796;
    background: #494d64;
}

#workspacePanelContent,
#workspacePlaceholder {
    background: transparent;
    border: none;
}

#workspacePlaceholderLabel {
    color: #8087a2;
    font-size: 13px;
    border: none;
}

QSplitter#workspaceSplitter::handle {
    background: #24273a;
}

QSplitter#workspaceSplitter::handle:hover {
    background: #8aadf4;
}
"""


def main() -> int:
    """Run a standalone demonstration of the embedded tiling workspace."""

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(WORKSPACE_STYLESHEET)

    window = QMainWindow()
    window.setWindowTitle("Arlo Workspace")
    window.resize(1200, 800)

    root = QWidget()
    root_layout = QVBoxLayout(root)
    root_layout.setContentsMargins(12, 12, 12, 12)
    root_layout.setSpacing(10)

    toolbar = QWidget()
    toolbar_layout = QHBoxLayout(toolbar)
    toolbar_layout.setContentsMargins(0, 0, 0, 0)

    add_button = QPushButton("New workspace")
    close_button = QPushButton("Close active")
    reset_button = QPushButton("Reset")

    toolbar_layout.addWidget(add_button)
    toolbar_layout.addWidget(close_button)
    toolbar_layout.addWidget(reset_button)
    toolbar_layout.addStretch()

    workspace = Workspace()

    root_layout.addWidget(toolbar)
    root_layout.addWidget(workspace, 1)

    window.setCentralWidget(root)

    counter = 0

    def add_workspace() -> None:
        nonlocal counter

        counter += 1

        workspace.open_panel(
            title=f"Workspace {counter}",
        )

    def close_active() -> None:
        if workspace.active_panel_id is not None:
            workspace.close_panel(workspace.active_panel_id)

    add_button.clicked.connect(add_workspace)
    close_button.clicked.connect(close_active)
    reset_button.clicked.connect(workspace.close_all)

    add_workspace()

    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
