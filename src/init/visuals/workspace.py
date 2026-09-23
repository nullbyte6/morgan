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

import uuid

from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtWidgets import *


class WorkspacePanel(QFrame):
    """An independently closable and draggable embedded panel."""

    close_requested = Signal(str)
    focus_requested = Signal(str)
    move_requested = Signal(str, str)
    MIME_TYPE = "application/x-arlo-workspace-panel"

    def __init__(
        self,
        panel_id: str,
        title: str,
        content: QWidget | None = None,
        parent: QWidget | None = None):
        super().__init__(parent)

        self.panel_id = panel_id
        self.title = title
        self._drag_start: QPoint | None = None

        self.setObjectName("workspacePanel")
        self.setProperty("workspacePanel", True)
        self.setFrameShape(QFrame.NoFrame)
        self.setMinimumSize(180, 140)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAcceptDrops(True)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self.header = QWidget(self)
        self.header.setObjectName("workspacePanelHeader")
        self.header.setFixedHeight(38)
        self.header.setCursor(Qt.OpenHandCursor)
        self.header.installEventFilter(self)

        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(12, 0, 6, 0)
        header_layout.setSpacing(8)

        self.title_label = QLabel(title, self.header)
        self.title_label.setObjectName("workspacePanelTitle")
        self.title_label.setAttribute(Qt.WA_TransparentForMouseEvents)

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
        self.set_content(content or self._create_placeholder())

        self.close_button.clicked.connect(
            lambda: self.close_requested.emit(self.panel_id)
        )

    def _create_placeholder(self) -> QWidget:
        """Create an empty surface for the standalone demonstration."""
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
        """Replace the embedded content."""

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
        """Update the panel title."""

        self.title = title
        self.title_label.setText(title)

    def eventFilter(self, watched, event):
        if watched is self.header:
            if event.type() == event.Type.MouseButtonPress:
                if event.button() == Qt.LeftButton:
                    self._drag_start = event.position().toPoint()
                    self.focus_requested.emit(self.panel_id)

            elif event.type() == event.Type.MouseMove:
                if self._drag_start is not None:
                    distance = (
                        event.position().toPoint() - self._drag_start
                    ).manhattanLength()

                    if distance >= QApplication.startDragDistance():
                        self._drag_start = None
                        self._start_drag()
                        return True

            elif event.type() == event.Type.MouseButtonRelease:
                self._drag_start = None

        return super().eventFilter(watched, event)

    def _start_drag(self) -> None:
        """Start a local drag containing this panel's stable identifier."""

        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(self.MIME_TYPE, QByteArray(self.panel_id.encode()))
        drag.setMimeData(mime)

        self.header.setCursor(Qt.ClosedHandCursor)

        try:
            drag.exec(Qt.MoveAction)
        finally:
            self.header.setCursor(Qt.OpenHandCursor)

    def dragEnterEvent(self, event):
        if self._accepts_drag(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._accepts_drag(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.setProperty("dropTarget", False)
        self._refresh_style()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        if not self._accepts_drag(event):
            event.ignore()
            return

        source_id = bytes(
            event.mimeData().data(self.MIME_TYPE)
        ).decode()

        self.move_requested.emit(source_id, self.panel_id)
        event.acceptProposedAction()

    def _accepts_drag(self, event) -> bool:
        mime = event.mimeData()

        if not mime.hasFormat(self.MIME_TYPE):
            return False

        source_id = bytes(mime.data(self.MIME_TYPE)).decode(
            errors="replace"
        )

        return source_id != self.panel_id

    def _refresh_style(self) -> None:
        self.style().unpolish(self)
        self.style().polish(self)

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


class SplitterAnimation(QVariantAnimation):
    """Animate splitter sizes without modifying child widget geometry."""

    def __init__(
        self,
        splitter: QSplitter,
        start_sizes: list[int],
        end_sizes: list[int],
        duration: int = 220,
        parent: QObject | None = None,
    ):
        super().__init__(parent)

        self.splitter = splitter
        self.start_sizes = start_sizes
        self.end_sizes = end_sizes

        self.setStartValue(0.0)
        self.setEndValue(1.0)
        self.setDuration(duration)
        self.setEasingCurve(QEasingCurve.OutCubic)

        self.valueChanged.connect(self._update_sizes)

    def _update_sizes(self, progress: float) -> None:
        if self.splitter is None:
            return

        sizes = [
            round(start + (end - start) * progress)
            for start, end in zip(self.start_sizes, self.end_sizes)
        ]

        self.splitter.setSizes(sizes)


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

        self._shortcut_counter = 0
        self._animations: dict[QSplitter, SplitterAnimation] = {}
        self._install_shortcuts()

        self._closing_panels: set[str] = set()

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

    def open_panel(self,
        title: str = "Workspace",
        content: QWidget | None = None,
        *,
        panel_id: str | None = None,
        target_id: str | None = None,
        orientation: Qt.Orientation | None = None) -> str:
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
        panel.move_requested.connect(self.swap_panels)

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



    def animate_splitter(
        self,
        splitter: QSplitter,
        start_sizes: list[int],
        end_sizes: list[int],
        duration: int = 220,
        on_finished=None) -> None:
        """Animate splitter sizes and invoke an optional completion callback."""
        previous = self._animations.pop(splitter, None)

        if previous is not None:
            previous.stop()
            previous.deleteLater()

        animation = SplitterAnimation(
            splitter,
            start_sizes,
            end_sizes,
            duration,
            self)

        self._animations[splitter] = animation

        def finish() -> None:
            if self._animations.get(splitter) is not animation:
                return

            self._animations.pop(splitter)
            splitter.setSizes(end_sizes)

            if on_finished is not None:
                on_finished()

            animation.deleteLater()

        animation.finished.connect(finish)
        animation.start()

    def _select_target(
        self,
        target_id: str | None) -> WorkspacePanel:
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
        orientation: Qt.Orientation) -> None:
        """Insert a panel and animate the new binary split."""
        parent = target.parentWidget()

        if isinstance(parent, QSplitter):
            index = parent.indexOf(target)
            original_sizes = parent.sizes()

            target.setParent(None)

            split = WorkspaceSplitter(orientation)
            split.addWidget(target)
            split.addWidget(panel)

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

        split.splitterMoved.connect(self._on_splitter_moved)

        available = (
            split.width()
            if orientation == Qt.Horizontal
            else split.height()) - split.handleWidth()

        available = max(available, 360)

        minimum = (
            panel.minimumWidth()
            if orientation == Qt.Horizontal
            else panel.minimumHeight())

        minimum = min(minimum, available // 2)

        start_sizes = [available - minimum, minimum]
        end_sizes = [available // 2, available - available // 2]

        split.setSizes(start_sizes)

        self.animate_splitter(
            split,
            start_sizes,
            end_sizes)


    def close_panel(self, panel_id: str) -> bool:
        """Animate panel removal and promote the surviving sibling."""

        panel = self._panels.get(panel_id)

        if panel is None:
            return False

        if panel_id in self._closing_panels:
            return False

        parent = panel.parentWidget()

        if not isinstance(parent, QSplitter):
            return self._remove_panel(panel_id)

        index = parent.indexOf(panel)
        sibling_index = 1 - index

        sizes = parent.sizes()
        total = sum(sizes)

        minimum = (
            panel.minimumWidth()
            if parent.orientation() == Qt.Horizontal
            else panel.minimumHeight()
        )

        minimum = min(minimum, total // 2)

        end_sizes = [0, 0]
        end_sizes[index] = minimum
        end_sizes[sibling_index] = total - minimum

        self._closing_panels.add(panel_id)
        panel.close_button.setEnabled(False)

        self.animate_splitter(
            parent,
            sizes,
            end_sizes,
            on_finished=lambda: self._remove_panel(panel_id),
        )

        return True

    def _remove_panel(self, panel_id: str) -> bool:
        """Remove a panel after its closing animation."""
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
                    "Workspace split must contain exactly two children")

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
        self._closing_panels.discard(panel_id)

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
        content: QWidget) -> bool:
        """Replace one panel's content without affecting neighboring panels."""

        panel = self._panels.get(panel_id)

        if panel is None:
            return False

        if content.isWindow():
            raise ValueError(
                "Workspace content must be an embedded QWidget")

        panel.set_content(content)

        return True


    def close_all(self) -> None:
        """Remove all panels and cancel pending layout animations."""
        for animation in tuple(self._animations.values()):
            animation.stop()
            animation.deleteLater()

        self._animations.clear()

        for panel_id in tuple(self._panels):
            self._remove_panel(panel_id)

    def _on_splitter_moved(self, position: int, index: int) -> None:
        self.layout_changed.emit()



    def _install_shortcuts(self) -> None:
        """Install keyboard shortcuts for the active workspace."""
        shortcuts = {
            "Ctrl+W": self.close_active_panel,
            "Ctrl+Alt+Left": lambda: self.focus_neighbor(Qt.LeftArrow),
            "Ctrl+Alt+Right": lambda: self.focus_neighbor(Qt.RightArrow),
            "Ctrl+Alt+Up": lambda: self.focus_neighbor(Qt.UpArrow),
            "Ctrl+Alt+Down": lambda: self.focus_neighbor(Qt.DownArrow),
        }

        self._shortcuts: list[QShortcut] = []

        for sequence, callback in shortcuts.items():
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)

    def _open_shortcut_panel(self) -> None:
        """Open a numbered placeholder panel."""

        self._shortcut_counter += 1
        self.open_panel(f"Workspace {self._shortcut_counter}")

    def close_active_panel(self) -> None:
        """Close the currently selected panel."""

        if self._active_panel_id is not None:
            self.close_panel(self._active_panel_id)

    def focus_neighbor(self, direction: Qt.Key) -> bool:
        """Focus the nearest panel in the requested screen direction."""

        current = self._panels.get(self._active_panel_id)

        if current is None:
            return False

        origin = current.mapToGlobal(current.rect().center())
        candidates = []

        for panel_id, panel in self._panels.items():
            if panel is current:
                continue

            position = panel.mapToGlobal(panel.rect().center())
            dx = position.x() - origin.x()
            dy = position.y() - origin.y()

            if direction == Qt.LeftArrow and dx >= 0:
                continue

            if direction == Qt.RightArrow and dx <= 0:
                continue

            if direction == Qt.UpArrow and dy >= 0:
                continue

            if direction == Qt.DownArrow and dy <= 0:
                continue

            primary = abs(dx) if direction in (
                Qt.LeftArrow, Qt.RightArrow
            ) else abs(dy)

            secondary = abs(dy) if direction in (
                Qt.LeftArrow, Qt.RightArrow
            ) else abs(dx)

            candidates.append((primary + secondary * 2, panel_id))

        if not candidates:
            return False

        _, panel_id = min(candidates)
        return self.focus_panel(panel_id)

    def swap_panels(self, source_id: str, target_id: str) -> bool:
        """Exchange two leaves while preserving their embedded widgets."""

        if source_id == target_id:
            return False

        source = self._panels.get(source_id)
        target = self._panels.get(target_id)

        if source is None or target is None:
            return False

        source_parent = source.parentWidget()
        target_parent = target.parentWidget()

        if not isinstance(source_parent, QSplitter):
            return False

        if not isinstance(target_parent, QSplitter):
            return False

        source_index = source_parent.indexOf(source)
        target_index = target_parent.indexOf(target)

        if source_parent is target_parent:
            source_parent.insertWidget(source_index, target)
            source_parent.insertWidget(target_index, source)

        else:
            source_sizes = source_parent.sizes()
            target_sizes = target_parent.sizes()

            source.setParent(None)
            target.setParent(None)

            source_parent.insertWidget(source_index, target)
            target_parent.insertWidget(target_index, source)

            source_parent.setSizes(source_sizes)
            target_parent.setSizes(target_sizes)

        self.focus_panel(source_id)
        self.layout_changed.emit()

        return True
