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
"""Live scaling of the complete widget interface, including custom painting."""

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QPainter, QShortcut, QTransform
from PySide6.QtWidgets import QApplication, QFrame, QGraphicsScene, QGraphicsView


class ZoomView(QGraphicsView):
    """Keep the interface in logical coordinates and scale its presentation."""
    zoom_changed = Signal(int)
    content_resized = Signal()
    MIN_ZOOM = 50
    MAX_ZOOM = 200
    ZOOM_STEP = 10

    def __init__(self, content, parent=None, zoom_percent=100):
        super().__init__(parent)
        self.setObjectName("globalZoomView")
        self.setFrameShape(QFrame.NoFrame)
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.NoAnchor)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing |
                            QPainter.SmoothPixmapTransform)
        self.setBackgroundBrush(Qt.NoBrush)
        self.setAutoFillBackground(False)
        self.viewport().setObjectName("globalZoomViewport")
        self.viewport().setAutoFillBackground(False)
        self.content = content
        content.setProperty("uiZoom", 100)
        self.zoom_percent = 100
        self._resizing_content = False
        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.timeout.connect(self._resize_content)

        self._zoom_shortcuts = []
        for sequence, direction in (
                ("Ctrl++", 1),
                ("Ctrl+=", 1),
                ("Ctrl+Shift+=", 1),
                ("Ctrl+-", -1),
                ("Ctrl+0", 0)):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ApplicationShortcut)
            shortcut.activated.connect(
                lambda direction=direction: self._apply_shortcut_zoom(direction))
            self._zoom_shortcuts.append(shortcut)

        scene = QGraphicsScene(self)
        self.setScene(scene)
        content.setAttribute(Qt.WA_TranslucentBackground)
        self.proxy = scene.addWidget(content)
        self.proxy.setPos(0, 0)
        content.installEventFilter(self)
        QApplication.instance().installEventFilter(self)
        self.set_zoom(zoom_percent)
        self._layout_timer.start(0)

    def _apply_shortcut_zoom(self, direction):
        if direction == 0:
            self.set_zoom(100)
        else:
            self.set_zoom(self.zoom_percent + direction * self.ZOOM_STEP)

    def set_zoom(self, percent):
        percent = max(self.MIN_ZOOM, min(self.MAX_ZOOM, int(percent)))
        if percent == self.zoom_percent:
            return
        self.zoom_percent = percent
        self.content.setProperty("uiZoom", percent)
        scale = percent / 100.0
        self.setTransform(QTransform.fromScale(scale, scale))
        self._resize_content()
        self.zoom_changed.emit(percent)

    def _resize_content(self):
        if self._resizing_content:
            return
        self._resizing_content = True
        try:
            scale = self.zoom_percent / 100.0
            available = QSize(max(1, int(self.viewport().width() / scale)),
                              max(1, int(self.viewport().height() / scale)))
            minimum = self.content.minimumSizeHint().expandedTo(self.content.minimumSize())
            target = available.expandedTo(minimum)
            changed = target != self.content.size()
            if changed:
                self.content.resize(target)
                if self.content.layout() is not None:
                    self.content.layout().activate()
            self.setSceneRect(QRectF(self.content.rect()))
            if changed:
                self.content_resized.emit()
        finally:
            self._resizing_content = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_content()

    def eventFilter(self, watched, event):
        if watched is self.content and event.type() == QEvent.LayoutRequest:
            self._layout_timer.start(0)
        # Some layouts deliver shifted plus as Key_Plus instead of Key_Equal;
        # handle that variant directly because QShortcut cannot match it
        # consistently across keyboard layouts.
        if (event.type() == QEvent.KeyPress
                and event.key() == Qt.Key_Plus
                and event.modifiers() & Qt.ControlModifier
                and QApplication.activeWindow() == self.window()):
            self._apply_shortcut_zoom(1)
            event.accept()
            return True
        return super().eventFilter(watched, event)
