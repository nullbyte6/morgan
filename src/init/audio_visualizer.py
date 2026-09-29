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

from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtWidgets import *

from .theme import current_theme, on_theme_changed

class AudioVisualizer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(100)
        self.setMinimumWidth(300)
        on_theme_changed(self.apply_theme)

        self.levels = [0.0] * 15
        self.smoothed = [0.0] * 15
        self.amplitude = 0.0
        self.phase = 0.0

        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.animate)
        self.timer.start()

    def set_levels(self, levels):
        self.levels = [max(0.0, min(1.0, float(level))) for level in
                       levels[:15]]
        self.levels.extend([0.0] * (15 - len(self.levels)))

    def clear(self):
        self.levels = [0.0] * 15

    def animate(self):
        for i, level in enumerate(self.levels):
            speed = 1.40 if level > self.smoothed[i] else 0.75
            self.smoothed[i] += (level - self.smoothed[i]) * speed

        target = max(self.smoothed)
        speed = 1.20 if target > self.amplitude else 0.60
        self.amplitude += (target - self.amplitude) * speed

        if self.amplitude < 0.001:
            self.amplitude = 0.0

        self.phase += 0.055 + self.amplitude * 0.045
        self.update()

    def apply_theme(self, theme):
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        width = self.width()
        height = self.height()
        center = height / 2

        theme = current_theme()
        colors = (
            theme.color("audio_wave_layer_1", 240),
            theme.color("audio_wave_layer_2", 150),
            theme.color("audio_wave_layer_3", 95),
            theme.color("audio_wave_layer_4", 55))

        for layer, color in enumerate(colors):
            path = QPainterPath()
            points = max(120, width // 3)

            for i in range(points + 1):
                t = i / points
                x = t * width

                envelope = max(0.0, 1.0 - ((t - 0.5) * 2.0) ** 2) ** 1.8

                band_position = t * 14
                band_index = min(13, int(band_position))
                fraction = band_position - band_index

                level = (self.smoothed[band_index] * (1.0 - fraction) +
                         self.smoothed[band_index + 1] * fraction)

                energy = self.amplitude * 0.45 + level * 0.55
                amplitude = (12.0 + layer * 7.0) * envelope * energy * 2.2

                wave = math.sin(
                    t * 26.0 - self.phase * (0.8 + layer * 0.08) + layer * 0.55
                )

                detail = math.sin(t * 43.0 + self.phase * 0.45) * 0.22

                y = center + (wave + detail) * amplitude

                if i == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)

            pen = QPen(color)
            pen.setWidthF(2.0 if layer == 0 else 1.5)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)

            painter.setPen(pen)
            painter.drawPath(path)

        painter.end()