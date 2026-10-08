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
"""Always-on-top compact composer shown while the main window is closed."""

import time

from PySide6.QtCore import QEasingCurve, QPoint, QRect, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QGuiApplication, QRegion
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLayout, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)


from src.init.audio_visualizer import AudioVisualizer
from src.init.chat import ChatInput

WIDTH = 248
MARGIN = 0
EDGE_GAP = 16
DURATION = 260


class CompactOverlay(QWidget):
    restore_requested = Signal()
    position_changed = Signal(int, int)

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setObjectName("compactOverlay")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._reveal = 1.0
        self._closing = False
        self._placed = False
        self._last_press = 0
        self._drag_offset = None

        self.input = ChatInput()
        self.input.file_tags_enabled = False
        self.meter = AudioVisualizer()
        self.meter.setMinimumWidth(0)
        self.meter.setFixedHeight(36)
        self.meter.hide()
        self.output = AudioVisualizer(color_role="text")
        self.output.setMinimumWidth(0)
        self.output.setFixedHeight(36)
        self.output.hide()
        self._recording = False
        self._responding = False
        self.send = QPushButton("")
        self.send.setObjectName("send")
        self.send.setFixedSize(32, 32)

        frame = QFrame()
        frame.setObjectName("inputFrame")
        frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        frame.setMinimumHeight(40)
        row = QHBoxLayout(frame)
        row.setContentsMargins(16, 2, 4, 2)
        row.setSpacing(0)
        row.addWidget(self.input, 1, Qt.AlignVCenter)
        row.addWidget(self.meter)
        row.addWidget(self.output)
        row.addWidget(self.send, 0, Qt.AlignVCenter)

        card = QFrame()
        card.setObjectName("overlayCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        card_layout.addWidget(frame)

        self.card = card

        self._subtitle_slot = QWidget()
        self._subtitle_slot.setFixedHeight(0)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.setSizeConstraint(QLayout.SetFixedSize)
        outer.addWidget(self._subtitle_slot)
        outer.addWidget(card)
        card.setFixedWidth(WIDTH)

        self._animation = QVariantAnimation(self)
        self._animation.setDuration(DURATION)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.valueChanged.connect(self._set_reveal)
        self._animation.finished.connect(self._finish_animation)

    def subtitle_anchor(self):
        return QRect(self.card.mapToGlobal(QPoint(0, 0)), self.card.size())

    def set_subtitle_space(self, height: int):
        if self._subtitle_slot.height() != height:
            self._subtitle_slot.setFixedHeight(height)

    def set_recording(self, recording: bool):
        self._recording = recording
        self._refresh_mode()

    def set_responding(self, responding: bool):
        self._responding = responding
        self._refresh_mode()

    def _refresh_mode(self):
        listening = self._recording
        answering = self._responding and not listening
        self.input.setVisible(not listening and not answering)
        self.meter.setVisible(listening)
        self.output.setVisible(answering)
        if not listening:
            self.meter.clear()
        if not answering:
            self.output.clear()

    def set_levels(self, levels):
        self.meter.set_levels(levels)

    def set_output_levels(self, levels):
        self.output.set_levels(levels)

    def sync_text(self, text: str):
        if self.input.toPlainText() != text:
            self.input.blockSignals(True)
            self.input.setPlainText(text)
            self.input.blockSignals(False)
            self.input.adjust_height()

    def open(self):
        self._closing = False
        if not self.isVisible():
            if not self._placed:
                self._place_default()
            self._set_reveal(0.0)
            self.show()
            self._clamp_to_screen()
        self.raise_()
        self._run(1.0)

    def close_animated(self):
        if not self.isVisible() or self._closing:
            return
        self._closing = True
        self._run(0.0)

    def _run(self, target):
        self._animation.stop()
        self._animation.setStartValue(self._reveal)
        self._animation.setEndValue(target)
        self._animation.start()

    def _set_reveal(self, value):
        self._reveal = float(value)
        self.setWindowOpacity(min(1.0, self._reveal * 1.6))
        if self._reveal >= 1.0:
            self.clearMask()
            return
        width = max(1, round(self.width() * self._reveal))
        left = (self.width() - width) // 2
        self.setMask(QRegion(QRect(left, 0, width, self.height())))

    def _finish_animation(self):
        if self._closing:
            self._closing = False
            self.hide()
            self.setWindowOpacity(1.0)
            self.clearMask()

    def restore_position(self, x, y):
        self.move(x, y)
        self._placed = True

    def _place_default(self):
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.layout().activate()
        hint = self.layout().sizeHint()
        self.move(screen.right() + 1 - hint.width() - EDGE_GAP,
                  screen.bottom() + 1 - hint.height() - EDGE_GAP)
        self._placed = True

    def _clamped(self, x, y):
        center = QPoint(x + self.width() // 2, y + self.height() // 2)
        screen = QGuiApplication.screenAt(center) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        return (max(area.left(), min(x, area.right() + 1 - self.width())),
                max(area.top(), min(y, area.bottom() + 1 - self.height())))

    def _clamp_to_screen(self):
        if not self.isVisible():
            return
        x, y = self._clamped(self.x(), self.y())
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        old = event.oldSize()
        if self.isVisible() and old.height() > 0 and old.height() != self.height():
            self.move(self.x(), self.y() - (self.height() - old.height()))
        self._clamp_to_screen()
        if self._reveal < 1.0:
            self._set_reveal(self._reveal)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._last_press = 0
            self._drag_offset = None
            self.restore_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            now = time.monotonic() * 1000
            if now - self._last_press <= QGuiApplication.styleHints().mouseDoubleClickInterval():
                self._last_press = 0
                self._drag_offset = None
                self.restore_requested.emit()
                event.accept()
                return
            self._last_press = now
            self._drag_offset = event.globalPosition().toPoint() - self.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            if QGuiApplication.platformName() == "wayland":
                self._drag_offset = None
                handle = self.windowHandle()
                if handle is not None:
                    handle.startSystemMove()
                event.accept()
                return
            target = event.globalPosition().toPoint() - self._drag_offset
            self.move(*self._clamped(target.x(), target.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._drag_offset is not None:
            self._drag_offset = None
            self.position_changed.emit(self.x(), self.y())
            event.accept()
            return
        super().mouseReleaseEvent(event)
