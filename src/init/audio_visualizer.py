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

        bar = 3.0
        gap = 5.0
        count = max(1, int((width + gap) // (bar + gap)))
        left = (width - (count * bar + (count - 1) * gap)) / 2
        max_half = height * 0.42
        min_half = bar / 2

        painter.setPen(Qt.NoPen)
        painter.setBrush(current_theme().color("accent"))

        for i in range(count):
            t = i / max(1, count - 1)
            envelope = 0.35 + 0.65 * math.sin(math.pi * t)

            band_position = t * 14
            band_index = min(13, int(band_position))
            fraction = band_position - band_index
            level = (self.smoothed[band_index] * (1.0 - fraction) +
                     self.smoothed[band_index + 1] * fraction)

            shimmer = 0.75 + 0.25 * math.sin(i * 0.9 - self.phase * 6.0)
            energy = min(1.0, (self.amplitude * 0.35 + level * 0.65) * 1.6)
            half = min_half + (max_half - min_half) * energy * envelope * shimmer

            x = left + i * (bar + gap)
            painter.drawRoundedRect(
                QRectF(x, center - half, bar, half * 2), bar / 2, bar / 2)

        painter.end()