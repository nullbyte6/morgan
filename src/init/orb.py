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
import random
import math
from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtWidgets import *


class Orb(QWidget):
    """Shared audio-reactive widget, embedded or floating.
    ``size`` is the preferred diameter in Qt logical pixels. Call ``set_size``
    to change it later, or let the layout resize the widget. Geometry scales
    with the available space; ``line_width`` stays in Qt logical pixels so
    small instances retain visible outlines. Change it with ``set_line_width``.
    ``fill_ratio`` controls the diameter of a centered, animated inner fill as
    a fraction of the main outline diameter.
    """
    _preferred_size: int
    line_width: float
    fill_ratio: float
    restore_requested = Signal()
    record_requested = Signal()

    COLORS = (
        QColor(245, 247, 255, 240),
        QColor(165, 181, 255, 165),
        QColor(116, 133, 240, 110),
        QColor(96, 113, 205, 65),
    )

    def __init__(self, parent=None, *,
                 size: int = 384,
                 floating: bool = False,
                 line_width: float = 8.0,
                 fill_ratio: float = 0.0):
        super().__init__(parent)
        self.floating = floating
        if floating:
            self.setWindowFlags(
                Qt.WindowType.Tool
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setObjectName("arloOrb")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.set_line_width(line_width)
        self.set_fill_ratio(fill_ratio)
        self.set_size(size)
        self.setToolTip("Arlo")

        self.levels = [0.0] * 15
        self.smoothed = [0.0] * 15

        self.amplitude = 0.0
        self.phase = 0.0
        self.ripple_phase = random.uniform(0.0, math.tau)
        self.ripple_seed = random.uniform(0.0, math.tau)
        self.speaking = False
        self.listening = False
        self.speech_pulse_enabled = True
        self.speech_scale = 1.0

        self.click_pulse = 0.0
        self.double_pulse = 0.0

        self._drag_origin = None
        self._drag_offset = None
        self._dragging = False
        self._suppress_release_click = False
        if floating:
            self.setCursor(Qt.CursorShape.OpenHandCursor)

        self.click_timer = QTimer(self)
        self.click_timer.setSingleShot(True)
        self.click_timer.timeout.connect(self._confirm_single_click)

        self.restore_timer = QTimer(self)
        self.restore_timer.setSingleShot(True)
        self.restore_timer.timeout.connect(self.restore_requested.emit)

        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.animate)
        self.timer.start()

    def sizeHint(self):
        return QSize(self._preferred_size, self._preferred_size)

    def minimumSizeHint(self):
        return QSize(24, 24)

    def set_size(self, size: int):
        """Change the preferred size without locking the widget's geometry."""
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise ValueError("Orb size must be a positive integer")
        self._preferred_size = size
        self.resize(size, size)
        self.updateGeometry()
        self.update()

    def set_line_width(self, line_width: float):
        """Set the main outline width in logical pixels, independent of size."""
        if (isinstance(line_width, bool) or not isinstance(line_width,
                                                           (int, float))
                or not math.isfinite(line_width) or line_width <= 0):
            raise ValueError("Orb line_width must be a positive finite number")
        self.line_width = float(line_width)
        self.update()

    def set_fill_ratio(self, fill_ratio: float):
        """Set the animated inner fill diameter relative to the main outline."""
        if (isinstance(fill_ratio, bool)
                or not isinstance(fill_ratio, (int, float))
                or not math.isfinite(fill_ratio)
                or not 0.0 <= fill_ratio <= 1.0):
            raise ValueError(
                "Orb fill_ratio must be a finite number from 0 to 1")
        self.fill_ratio = float(fill_ratio)
        self.update()

    def set_levels(self, levels):
        values = list(levels)[:15]
        self.levels = [max(0.0, min(1.0, float(value)))
                       for value in values]

        self.levels.extend([0.0] * (15 - len(self.levels)))

    def set_speaking(self, speaking: bool):
        self.speaking = speaking
        if not speaking:
            self.clear()

    def set_listening(self, listening: bool):
        """Let microphone intensity directly resize a recording mascot."""
        self.listening = bool(listening)
        if not listening:
            self.clear()

    def set_speech_pulse_enabled(self, enabled: bool):
        self.speech_pulse_enabled = bool(enabled)

    def clear(self):
        self.levels = [0.0] * 15

    def animate(self):
        for index, target in enumerate(self.levels):
            current = self.smoothed[index]
            factor = 0.65 if target > current else 0.16
            self.smoothed[index] += (target - current) * factor

        target = max(self.smoothed)
        factor = (0.55 if target > self.amplitude
                  else 0.12)

        self.amplitude += (target - self.amplitude) * factor
        if self.amplitude < 0.0005:
            self.amplitude = 0.0

        speech_scale_target = 1.0
        if self.listening:
            speech_scale_target = 0.94 + self.amplitude * 0.14
        elif self.speaking and self.speech_pulse_enabled:
            speech_scale_target = 0.965 + self.amplitude * 0.10
        scale_factor = (0.28 if speech_scale_target > self.speech_scale
                        else 0.18)
        self.speech_scale += (speech_scale_target - self.speech_scale) * scale_factor

        self.phase += (0.025 + self.amplitude * 0.045)
        self.ripple_phase += 0.008

        self.click_pulse *= 0.88
        self.double_pulse *= 0.93

        if self.click_pulse < 0.001:
            self.click_pulse = 0.0

        if self.double_pulse < 0.001:
            self.double_pulse = 0.0

        self.update()

    def paintEvent(self, event):
        side = min(self.width(), self.height())
        if side <= 0:
            return
        scale = side / 320.0
        painter = QPainter(self)
        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing)

        side = min(self.width(), self.height())
        painter.translate(self.width() / 2, self.height() / 2)
        painter.scale(scale * self.speech_scale,
                      scale * self.speech_scale)
        points = 240
        for layer, color in enumerate(self.COLORS):
            path = QPainterPath()
            fill_path = QPainterPath() if layer == 0 and self.fill_ratio else None
            base_radius = 102.4 + layer * 3.0
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

                energy = (self.amplitude * 0.35 + level * 0.65)
                energy = min(1.0, energy * 2.0) ** 0.7

                idle = math.sin(
                    angle * 3.0 - self.phase * 0.5) * 0.45

                ripple = (math.sin(angle * 5.0
                                   + self.ripple_phase * 0.75
                                   + self.ripple_seed) * 0.75 + math.sin(
                    angle * 9.0
                    - self.ripple_phase * 0.43
                    + self.ripple_seed * 1.7) * 0.35 + math.sin(angle * 13.0
                                                                + self.ripple_phase * 0.27
                                                                + self.ripple_seed * 0.6) * 0.15)

                ripple *= 1.2 + layer * 0.08

                deformation = ((primary + secondary + detail)
                               * energy * (9.0 + layer * 1.2))

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

                breathing = (math.sin(self.phase * 0.8) * 0.8)
                voice_expansion = (self.amplitude * 6.0)

                radius = (base_radius + deformation + idle + breathing +
                          ripple + voice_expansion + click_effect +
                          double_effect + expansion)

                x = math.cos(angle) * radius
                y = math.sin(angle) * radius

                if index == 0:
                    path.moveTo(x, y)
                    if fill_path is not None:
                        fill_path.moveTo(
                            x * self.fill_ratio, y * self.fill_ratio)
                else:
                    path.lineTo(x, y)
                    if fill_path is not None:
                        fill_path.lineTo(
                            x * self.fill_ratio, y * self.fill_ratio)

            path.closeSubpath()

            if fill_path is not None:
                fill_path.closeSubpath()
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(self.COLORS[0])
                painter.drawPath(fill_path)

            pen = QPen(color)
            pen.setWidthF(
                self.line_width * (1.0 if layer == 0 else 1.5 / 2.2) / scale)
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
        margin = round(min(self.width(), self.height()) / 6)

        self.move(
            area.right() - self.width() - margin + 1,
            area.bottom() - self.height() - margin + 1)

    def mousePressEvent(self, event):
        if self.floating and event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint()
            self._drag_offset = event.position().toPoint()
            self._dragging = False
            self._suppress_release_click = False
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self.floating and self._drag_origin is not None
                and event.buttons() & Qt.MouseButton.LeftButton):
            global_position = event.globalPosition().toPoint()
            distance = (global_position - self._drag_origin).manhattanLength()
            if not self._dragging:
                if distance < QApplication.startDragDistance():
                    event.accept()
                    return
                self._dragging = True
                self.click_timer.stop()
                self.restore_timer.stop()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self.raise_()

            target = global_position - self._drag_offset
            screen = (
                    QApplication.screenAt(global_position)
                    or QApplication.screenAt(target)
                    or QApplication.primaryScreen())
            if screen is not None:
                area = screen.availableGeometry()
                target.setX(max(
                    area.left(),
                    min(target.x(), area.right() - self.width() + 1)))
                target.setY(max(
                    area.top(),
                    min(target.y(), area.bottom() - self.height() + 1)))

            self.move(target)
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.floating and event.button() == Qt.MouseButton.LeftButton:
            was_dragging = self._dragging
            suppress_click = self._suppress_release_click
            self._drag_origin = None
            self._drag_offset = None
            self._dragging = False
            self._suppress_release_click = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)

            if not was_dragging and not suppress_click:
                self.click_timer.start(QApplication.doubleClickInterval())

            event.accept()
            return

        super().mouseReleaseEvent(event)

    def _confirm_single_click(self):
        """Trigger a visual pulse and request recording."""
        self.click_pulse = 1.0
        self.record_requested.emit()

    def mouseDoubleClickEvent(self, event):
        if self.floating and event.button() == Qt.MouseButton.LeftButton:
            self.click_timer.stop()
            self._suppress_release_click = True

            self.double_pulse = 1.0
            self.restore_timer.start(220)

            event.accept()
            return

        super().mouseDoubleClickEvent(event)

    def hideEvent(self, event):
        self.click_timer.stop()
        self.restore_timer.stop()
        self._drag_origin = None
        self._drag_offset = None
        self._dragging = False
        self._suppress_release_click = False
        if self.floating:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().hideEvent(event)
