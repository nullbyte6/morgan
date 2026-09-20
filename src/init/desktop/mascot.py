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
import math

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget, QApplication


class ArloMascot(QWidget):
    """Floating, audio-reactive Arlo mascot."""
    restore_requested = Signal()
    record_requested = Signal()

    COLORS = (
        QColor(245, 247, 255, 240),
        QColor(165, 181, 255, 165),
        QColor(116, 133, 240, 110),
        QColor(96, 113, 205, 65),
    )

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )

        self.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground
        )

        self.setObjectName("arloMascot")
        self.setFixedSize(120, 120)
        self.setToolTip("Arlo!")

        self.levels = [0.0] * 15
        self.smoothed = [0.0] * 15

        self.amplitude = 0.0
        self.phase = 0.0
        self.speaking = False

        self.click_pulse = 0.0
        self.double_pulse = 0.0

        self.click_timer = QTimer(self)
        self.click_timer.setSingleShot(True)
        self.click_timer.timeout.connect(self._confirm_single_click)

        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.animate)
        self.timer.start()

    def set_levels(self, levels):
        values = list(levels)[:15]

        self.levels = [max(0.0, min(1.0, float(value)))
            for value in values]

        self.levels.extend([0.0] * (15 - len(self.levels)))

    def set_speaking(self, speaking: bool):
        self.speaking = speaking

        if not speaking:
            self.clear()

    def clear(self):
        self.levels = [0.0] * 15

    def animate(self):
        for index, target in enumerate(self.levels):
            current = self.smoothed[index]
            factor = 0.38 if target > current else 0.12
            self.smoothed[index] += (target - current) * factor

        target = max(self.smoothed)
        factor = (0.30 if target > self.amplitude
            else 0.10)

        self.amplitude += (target - self.amplitude) * factor
        if self.amplitude < 0.0005:
            self.amplitude = 0.0

        self.phase += (0.025 + self.amplitude * 0.045)

        self.click_pulse *= 0.88
        self.double_pulse *= 0.93

        if self.click_pulse < 0.001:
            self.click_pulse = 0.0

        if self.double_pulse < 0.001:
            self.double_pulse = 0.0

        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing)

        center_x = self.width() / 2
        center_y = self.height() / 2
        points = 240
        for layer, color in enumerate(self.COLORS):
            path = QPainterPath()
            base_radius = 23.0 + layer * 3.0
            for index in range(points + 1):
                t = index / points
                angle = t * math.tau

                position = t * 15
                band = int(position) % 15
                next_band = (band + 1) % 15
                fraction = position - int(position)

                fraction = (
                    fraction * fraction
                    * (3.0 - 2.0 * fraction))

                level = (
                    self.smoothed[band] * (1.0 - fraction)
                    + self.smoothed[next_band] * fraction)

                primary = math.sin(
                    angle * 4.0
                    - self.phase * (1.0 + layer * 0.07)
                    + layer * 0.45)

                secondary = math.sin(
                    angle * 7.0
                    + self.phase * 0.63
                    + layer * 0.32) * 0.35

                detail = math.sin(
                    angle * 11.0
                    - self.phase * 0.37) * 0.12

                energy = (
                    self.amplitude * 0.45
                    + level * 0.55)

                idle = math.sin(
                    angle * 3.0 - self.phase * 0.5) * 0.45

                deformation = (
                    (primary + secondary + detail)
                    * energy
                    * (10.0 + layer * 1.8))

                click_wave = math.sin(
                    angle * 3.0
                    - self.phase * 2.5
                    - layer * 0.65)

                click_effect = (
                        click_wave
                        * self.click_pulse
                        * (3.0 + layer * 0.8))

                double_wave = math.sin(
                    angle * 2.0
                    + self.phase * 3.0
                    - layer * 0.9)

                double_effect = (
                        double_wave
                        * self.double_pulse
                        * (5.0 + layer * 1.2))

                expansion = (
                        self.click_pulse * 1.5
                        + self.double_pulse * 4.0)

                radius = (base_radius + deformation + idle + click_effect +
                        double_effect +
                        expansion)

                x = center_x + math.cos(angle) * radius
                y = center_y + math.sin(angle) * radius

                if index == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)

            path.closeSubpath()

            pen = QPen(color)
            pen.setWidthF(
                2.2 if layer == 0 else 1.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

        painter.end()

    def move_to_corner(self):
        screen = (
            QApplication.screenAt(self.pos())
            or QApplication.primaryScreen())

        if screen is None:
            return

        area = screen.availableGeometry()
        margin = 20

        self.move(
            area.right() - self.width() - margin + 1,
            area.bottom() - self.height() - margin + 1)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.click_timer.start(
                QApplication.doubleClickInterval()
            )
            event.accept()
            return

        super().mousePressEvent(event)

    def _confirm_single_click(self):
        """Trigger a visual pulse and request recording."""
        self.click_pulse = 1.0
        self.record_requested.emit()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.click_timer.stop()

            self.double_pulse = 1.0
            QTimer.singleShot(220,
                self.restore_requested.emit)

            event.accept()
            return

        super().mouseDoubleClickEvent(event)
