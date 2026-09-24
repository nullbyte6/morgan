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
from shiboken6 import isValid


class WorkspacePanel(QFrame):
    """An independently closable and draggable embedded panel."""

    close_requested = Signal(str)
    focus_requested = Signal(str)
    move_requested = Signal(str, str)
    title_changed = Signal(str, str)
    MIME_TYPE = "application/x-arlo-workspace-panel"

    def __init__(
        self,
        panel_id: str,
        title: str,
        content: QWidget | None = None,
        closable: bool = True,
        parent: QWidget | None = None):
        super().__init__(parent)

        self.panel_id = panel_id
        self.title = title
        self.closable = closable
        self.renamable = closable
        self._drag_start: QPoint | None = None
        self._dragging = False
        self._drag_target = None

        self.setObjectName("workspacePanel")
        self.setProperty("workspacePanel", True)
        self.setFrameShape(QFrame.NoFrame)
        # Let the splitter shrink the surface to zero; child painting is clipped
        # by the panel instead of imposing content minimums on the whole tree.
        self.setMinimumSize(0, 0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAcceptDrops(True)

        self._layout = QVBoxLayout(self)
        self._layout.setSizeConstraint(QLayout.SetNoConstraint)
        self._layout.setContentsMargins(6, 6, 6, 6)
        self._layout.setSpacing(6)

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

        self.title_edit = QLineEdit(title, self.header)
        self.title_edit.setObjectName("workspacePanelTitleEdit")
        self.title_edit.setFrame(False)
        self.title_edit.hide()
        self.title_edit.editingFinished.connect(self._finish_rename)

        self.close_button = QPushButton("×", self.header)
        self.close_button.setObjectName("workspacePanelClose")
        self.close_button.setFixedSize(28, 28)
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.setToolTip("Close panel")
        self.close_button.setVisible(closable)

        header_layout.addWidget(self.title_label, 1)
        header_layout.addWidget(self.title_edit, 1)
        header_layout.addWidget(self.close_button)

        self._layout.addWidget(self.header)

        self.content_host = QWidget(self)
        self.content_host.setObjectName("workspacePanelContent")

        self.content_layout = QVBoxLayout(self.content_host)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)

        self._layout.addWidget(self.content_host, 1)

        self.drop_preview = QFrame(self)
        self.drop_preview.setObjectName("workspaceDropPreview")
        self.drop_preview.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.drop_preview.setStyleSheet(
            "background-color: rgba(138, 173, 244, 72);"
            "border: 2px solid rgba(138, 173, 244, 210);"
            "border-radius: 10px;")
        self.drop_preview.hide()

        self.content: QWidget | None = None
        self.set_content(content or self._create_placeholder())

        self.close_button.clicked.connect(
            lambda: self.close_requested.emit(self.panel_id)
        )

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 0)

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
            self.dispose_content()
            if previous.property("workspaceViewKey") == "editor":
                previous.windowTitleChanged.disconnect(self.set_title)
            self.content_layout.removeWidget(previous)
            previous.setParent(None)
            previous.deleteLater()

        self.content = content
        self.content_layout.addWidget(content)
        self.setProperty("workspaceViewKey", content.property("workspaceViewKey"))
        self.style().unpolish(self)
        self.style().polish(self)
        if content.property("workspaceViewKey") == "editor":
            content.windowTitleChanged.connect(self.set_title)
            self.set_title(content.windowTitle())
            self.set_renamable(False)
        else:
            self.set_renamable(self.closable)

    def dispose_content(self) -> None:
        """Release content-owned resources before deferred widget deletion."""
        dispose = getattr(self.content, "dispose", None)
        if callable(dispose):
            dispose()

    def set_title(self, title: str) -> None:
        """Update the panel title."""

        title = title.strip() or self.title
        self.title = title
        self.title_label.setText(title)
        self.title_edit.setText(title)

    def set_renamable(self, enabled: bool) -> None:
        """Enable or disable inline title editing."""
        self.renamable = enabled

    def _begin_rename(self) -> None:
        if not self.renamable:
            return

        self.title_edit.setText(self.title)
        self.title_label.hide()
        self.title_edit.show()
        self.title_edit.selectAll()
        self.title_edit.setFocus(Qt.MouseFocusReason)

    def _finish_rename(self) -> None:
        if not self.title_edit.isVisible():
            return

        previous = self.title
        self.set_title(self.title_edit.text())
        self.title_edit.hide()
        self.title_label.show()
        self.title_changed.emit(previous, self.title)

    def eventFilter(self, watched, event):
        if watched is self.header:
            if event.type() == event.Type.MouseButtonPress:
                if event.button() == Qt.LeftButton:
                    self._drag_start = event.position().toPoint()
                    self.focus_requested.emit(self.panel_id)
                    event.accept()
                    return True

            elif event.type() == event.Type.MouseMove:
                if self._drag_start is not None:
                    distance = (
                        event.position().toPoint() - self._drag_start
                    ).manhattanLength()

                    if self._dragging or distance >= QApplication.startDragDistance():
                        self._dragging = True
                        self.header.setCursor(Qt.ClosedHandCursor)
                        self._update_panel_drag(event.position().toPoint())
                        return True

            elif event.type() == event.Type.MouseButtonRelease:
                self._drag_start = None
                target = self._drag_target
                self._clear_panel_drag()
                if target is not None:
                    self.move_requested.emit(self.panel_id, target.panel_id)
                event.accept()
                return True

            elif event.type() == event.Type.MouseButtonDblClick:
                if event.button() == Qt.LeftButton:
                    self._drag_start = None
                    self._begin_rename()
                    return True

        return super().eventFilter(watched, event)

    def _update_panel_drag(self, position: QPoint) -> None:
        """Use logical widget coordinates, also inside a scaled graphics proxy."""
        workspace = self.parentWidget()
        while workspace is not None and not isinstance(workspace, Workspace):
            workspace = workspace.parentWidget()
        if workspace is None or workspace._closing_panels:
            self._clear_panel_drag()
            return
        workspace._stop_opening_animations()
        target = workspace.childAt(self.header.mapTo(workspace, position))
        while target is not None and not isinstance(target, WorkspacePanel):
            target = target.parentWidget()
        if self._drag_target is not None:
            self._drag_target._clear_drop_preview()
        self._drag_target = target if target is not self else None
        if self._drag_target is not None:
            preview = self._drag_target.drop_preview
            preview.setGeometry(self._drag_target.rect().adjusted(6, 6, -6, -6))
            preview.show()
            preview.raise_()

    def _clear_panel_drag(self) -> None:
        if self._drag_target is not None:
            self._drag_target._clear_drop_preview()
        self._drag_target = None
        self._dragging = False
        self.header.setCursor(Qt.OpenHandCursor)

    def dragEnterEvent(self, event):
        if self._accepts_drag(event):
            self._update_drop_preview(event.position().toPoint())
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._accepts_drag(event):
            self._update_drop_preview(event.position().toPoint())
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._clear_drop_preview()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        if not self._accepts_drag(event):
            event.ignore()
            return

        self._clear_drop_preview()

        source_id = bytes(
            event.mimeData().data(self.MIME_TYPE)
        ).decode()

        self.move_requested.emit(source_id, self.panel_id)
        event.acceptProposedAction()

    def _update_drop_preview(self, position: QPoint) -> None:
        """Show the drop shape selected by the pointer position."""
        margin = 6
        rect = self.rect().adjusted(margin, margin, -margin, -margin)
        x_ratio = position.x() / max(1, self.width())
        y_ratio = position.y() / max(1, self.height())
        if x_ratio < 0.25:
            rect.setWidth(max(1, rect.width() // 2))
        elif x_ratio > 0.75:
            half = max(1, rect.width() // 2)
            rect.setLeft(rect.right() - half)
        elif y_ratio < 0.25:
            rect.setHeight(max(1, rect.height() // 2))
        elif y_ratio > 0.75:
            half = max(1, rect.height() // 2)
            rect.setTop(rect.bottom() - half)
        self.drop_preview.setGeometry(rect)
        self.drop_preview.show()
        self.drop_preview.raise_()

    def _clear_drop_preview(self) -> None:
        self.drop_preview.hide()

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


class WorkspaceSplitterHandle(QSplitterHandle):
    """Resize in local coordinates; native global positions ignore UI zoom."""

    def mousePressEvent(self, event):
        self._offset = None
        if event.button() == Qt.LeftButton:
            workspace = self.splitter().parentWidget()
            while workspace is not None and not isinstance(workspace, Workspace):
                workspace = workspace.parentWidget()
            if workspace is not None:
                if workspace._closing_panels:
                    event.ignore()
                    return
                workspace._stop_opening_animations()
            self._offset = event.position().toPoint()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if getattr(self, "_offset", None) is not None and event.buttons() & Qt.LeftButton:
            position = self.mapTo(self.splitter(), event.position().toPoint() - self._offset)
            value = position.x() if self.orientation() == Qt.Horizontal else position.y()
            self.moveSplitter(value)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._offset = None
        super().mouseReleaseEvent(event)


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

    def createHandle(self):
        return WorkspaceSplitterHandle(self.orientation(), self)


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

        # A permanent outer split reveals the entire workspace, including the
        # first chat panel, without moving or rebuilding any of its contents.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._surface = QSplitter(Qt.Vertical, self)
        self._surface.setHandleWidth(0)
        host = QWidget()
        host.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self._surface.addWidget(host)
        self._surface.addWidget(QWidget())
        self._surface.handle(1).setEnabled(False)
        outer.addWidget(self._surface)
        self._surface.setSizes([10000, 0])
        self._layout = QVBoxLayout(host)
        self._layout.setSizeConstraint(QLayout.SetNoConstraint)
        self._layout.setContentsMargins(6, 6, 6, 8)
        self._layout.setSpacing(6)

        self.manual_content_factory = None
        self._shortcut_counter = 0
        self._animations: dict[QSplitter, SplitterAnimation] = {}
        self._install_shortcuts()

        self._closing_panels: set[str] = set()
        self._pending_closes: list[str] = []
        self._surface_focus = None
        self._surface_active_id = None

        self.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Expanding,
        )

    @property
    def panel_count(self) -> int:
        return len(self._panels)

    def animate_visibility(self, expanded: bool, *, restart=False, on_finished=None):
        """Reveal/collapse the intact panel tree before the window is hidden."""
        if not expanded:
            focus = self.focusWidget()
            if focus is not None and self.isAncestorOf(focus):
                self._surface_focus = focus
                self._surface_active_id = self._active_panel_id

        def finish():
            focus = self._surface_focus
            if (expanded and focus is not None and isValid(focus)
                    and self._active_panel_id == self._surface_active_id
                    and focus.isVisible()):
                focus.setFocus(Qt.OtherFocusReason)
            if on_finished is not None:
                on_finished()

        sizes = self._surface.sizes()
        total = max(1, sum(sizes))
        start = ([0, 10000] if restart else
                 [round(size * 10000 / total) for size in sizes])
        self._surface.setSizes(start)
        self.animate_splitter(self._surface, start,
                              [10000, 0] if expanded else [0, 10000],
                              duration=260, on_finished=finish)

    def _stop_opening_animations(self):
        """Give a user dragging a handle control of the current sizes."""
        if self._closing_panels:
            return
        for splitter, animation in tuple(self._animations.items()):
            if splitter is not self._surface:
                self._animations.pop(splitter)
                animation.stop()
                animation.deleteLater()

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
        orientation: Qt.Orientation | None = None,
        direction: Qt.Key | None = None) -> str:
        """Insert a new panel by splitting an existing workspace leaf."""

        if direction is not None:
            if direction not in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
                raise ValueError(f"Invalid split direction: {direction}")
            orientation = (Qt.Horizontal if direction in (Qt.Key_Left, Qt.Key_Right)
                           else Qt.Vertical)
        panel_id = panel_id or uuid.uuid4().hex


        if panel_id in self._panels:
            raise ValueError(f"Panel already exists: {panel_id}")

        if content is not None and content.parentWidget() is not None:
            raise ValueError(
                "Workspace content must not belong to another widget")

        if target_id is not None and target_id not in self._panels:
            raise ValueError(f"Unknown target panel: {target_id}")

        panel = WorkspacePanel(
            panel_id=panel_id,
            title=title,
            content=content,
            closable=panel_id != getattr(self, "_primary_panel_id", None),
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

            self._insert_panel(target, panel, orientation,
                               before=direction in (Qt.Key_Left, Qt.Key_Up))

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

    def set_primary_panel(self, panel_id: str) -> bool:
        """Mark one panel as permanent and keep it available in the workspace."""
        if panel_id not in self._panels:
            return False

        previous = getattr(self, "_primary_panel_id", None)
        if previous in self._panels and previous != panel_id:
            self._panels[previous].closable = True
            self._panels[previous].set_renamable(True)
            self._panels[previous].close_button.setVisible(True)

        self._primary_panel_id = panel_id
        panel = self._panels[panel_id]
        panel.closable = False
        panel.set_renamable(False)
        panel.close_button.setVisible(False)
        return True



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

        if target_id is not None and target_id not in self._closing_panels:
            return self._panels[target_id]

        if (self._active_panel_id in self._panels
                and self._active_panel_id not in self._closing_panels):
            return self._panels[self._active_panel_id]

        return next(panel for key, panel in self._panels.items()
                    if key not in self._closing_panels)


    def _insert_panel(
        self,
        target: WorkspacePanel,
        panel: WorkspacePanel,
        orientation: Qt.Orientation,
        *, before: bool = False) -> None:
        """Insert a panel and animate the new binary split."""
        parent = target.parentWidget()
        focus = self.focusWidget()
        extent = target.width() if orientation == Qt.Horizontal else target.height()
        split = WorkspaceSplitter(orientation)

        if isinstance(parent, QSplitter):
            index = parent.indexOf(target)
            original_sizes = parent.sizes()

            parent.replaceWidget(index, split)
            # replaceWidget preserves geometry but PySide does not transfer
            # Python ownership of the replacement. insertWidget does both.
            parent.insertWidget(index, split)
            split.addWidget(target)
            split.addWidget(panel)

            if len(original_sizes) == parent.count():
                parent.setSizes(original_sizes)

        else:
            self._layout.replaceWidget(target, split)
            split.addWidget(target)
            split.addWidget(panel)

            self._root = split

        split.splitterMoved.connect(self._on_splitter_moved)
        if before:
            split.insertWidget(0, panel)

        available = max(1000, extent - split.handleWidth())
        start_sizes = [available, 0]
        if before:
            start_sizes.reverse()
        end_sizes = [available // 2, available - available // 2]

        split.setSizes(start_sizes)
        split.show()
        target.show()
        panel.show()
        if focus is not None and target.isAncestorOf(focus):
            focus.setFocus(Qt.OtherFocusReason)

        self.animate_splitter(
            split,
            start_sizes,
            end_sizes)


    def close_panel(self, panel_id: str) -> bool:
        """Animate panel removal and promote the surviving sibling."""

        panel = self._panels.get(panel_id)

        if panel is None:
            return False

        if panel_id == getattr(self, "_primary_panel_id", None):
            return False

        if panel_id in self._closing_panels or panel_id in self._pending_closes:
            return False

        if self._closing_panels:
            self._pending_closes.append(panel_id)
            return True

        parent = panel.parentWidget()

        if not isinstance(parent, QSplitter):
            return self._remove_panel(panel_id)

        index = parent.indexOf(panel)
        sibling_index = 1 - index

        sizes = parent.sizes()
        total = sum(sizes)

        end_sizes = [0, 0]
        end_sizes[sibling_index] = total

        self._closing_panels.add(panel_id)
        for other in self._panels.values():
            other._clear_panel_drag()
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
        focus = self.focusWidget()
        restore_focus = (focus is not None and focus is not panel
                         and not panel.isAncestorOf(focus))

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

            sibling.show()
            if restore_focus:
                focus.setFocus(Qt.OtherFocusReason)

        else:
            self._layout.removeWidget(panel)
            panel.setParent(None)
            self._root = None

        del self._panels[panel_id]
        self._closing_panels.discard(panel_id)

        panel.dispose_content()
        panel.deleteLater()

        if self._active_panel_id == panel_id:
            self._active_panel_id = None

            if self._panels:
                self.focus_panel(next(reversed(self._panels)))

        self.panel_closed.emit(panel_id)
        self.layout_changed.emit()

        while self._pending_closes and not self._closing_panels:
            next_id = self._pending_closes.pop(0)
            self.close_panel(next_id)

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

        if content.parentWidget() is not None:
            raise ValueError(
                "Workspace content must not belong to another widget")

        panel.set_content(content)

        return True

    def open_registered_panel(self, key: str, title: str,
                              content_factory, *,
                              orientation: Qt.Orientation | None = None) -> str:
        """Open a fresh configured panel instance in this workspace."""
        content = content_factory()
        content.setProperty("workspaceViewKey", key)
        return self.open_panel(title=title, content=content,
                               orientation=orientation)

    def close_all(self) -> None:
        """Remove all panels and cancel pending layout animations."""
        for animation in tuple(self._animations.values()):
            animation.stop()
            animation.deleteLater()

        self._animations.clear()
        self._pending_closes.clear()
        self._closing_panels.clear()

        primary_id = getattr(self, "_primary_panel_id", None)
        for panel_id in tuple(self._panels):
            if panel_id != primary_id:
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
            shortcut.setContext(Qt.ApplicationShortcut)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)

    def _open_shortcut_panel(self, direction: Qt.Key | None = None) -> None:
        """Open a manually created workspace."""
        counter = getattr(self, "_shortcut_counter", 0) + 1
        self._shortcut_counter = counter

        content = (
            self.manual_content_factory()
            if self.manual_content_factory is not None
            else None)

        self.open_panel(
            title=f"Workspace {counter}",
            content=content,
            direction=direction)

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

        if self._closing_panels:
            return False

        source = self._panels.get(source_id)
        target = self._panels.get(target_id)

        if source is None or target is None:
            return False

        self._stop_opening_animations()
        focus = self.focusWidget()

        source_parent = source.parentWidget()
        target_parent = target.parentWidget()

        source_is_splitter = isinstance(source_parent, QSplitter)
        target_is_splitter = isinstance(target_parent, QSplitter)

        source_index = (source_parent.indexOf(source)
                        if source_is_splitter else self._layout.indexOf(source))
        target_index = (target_parent.indexOf(target)
                        if target_is_splitter else self._layout.indexOf(target))

        source_sizes = source_parent.sizes() if source_is_splitter else None
        target_sizes = target_parent.sizes() if target_is_splitter else None

        source_placeholder = QWidget()
        target_placeholder = QWidget()
        if source_is_splitter:
            source_parent.replaceWidget(source_index, source_placeholder)
        else:
            self._layout.replaceWidget(source, source_placeholder)
        if target_is_splitter:
            target_parent.replaceWidget(target_index, target_placeholder)
        else:
            self._layout.replaceWidget(target, target_placeholder)

        if source_is_splitter:
            source_parent.replaceWidget(source_index, target)
            source_parent.insertWidget(source_index, target)
        else:
            self._layout.replaceWidget(source_placeholder, target)
            self._root = target
        if target_is_splitter:
            target_parent.replaceWidget(target_index, source)
            target_parent.insertWidget(target_index, source)
        else:
            self._layout.replaceWidget(target_placeholder, source)
            self._root = source

        if source_is_splitter:
            source_parent.setSizes(source_sizes)
        if target_is_splitter and target_parent is not source_parent:
            target_parent.setSizes(target_sizes)
        for parent, placeholder in (
            (source_parent, source_placeholder),
            (target_parent, target_placeholder),
        ):
            if isinstance(parent, QSplitter):
                if parent.indexOf(placeholder) >= 0:
                    parent.widget(parent.indexOf(placeholder)).setParent(None)
            else:
                self._layout.removeWidget(placeholder)
                placeholder.setParent(None)
        source_placeholder.deleteLater()
        target_placeholder.deleteLater()
        source.show()
        target.show()
        if focus is not None:
            focus.setFocus(Qt.OtherFocusReason)

        self.focus_panel(source_id)
        self.layout_changed.emit()

        return True
