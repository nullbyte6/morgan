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
from enum import Enum
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

    class State(str, Enum):
        IDLE = "idle"
        PROCESSING = "processing"
        READING = "reading"
        WRITING = "writing"
        EXECUTING = "executing"
        AWAITING_PERMISSION = "awaiting_permission"
        DENIED_ERROR = "denied_error"
        SUCCESS = "success"

    STATE_PROFILES = {
        State.IDLE: (0.018, 0.10, 0.0, "lavender"),
        State.PROCESSING: (0.040, 0.52, 0.0, "sapphire"),
        State.READING: (0.025, 0.42, 0.0, "blue"),
        State.WRITING: (0.055, 0.62, 0.0, "lavender"),
        State.EXECUTING: (0.075, 0.70, 0.085, "peach"),
        State.AWAITING_PERMISSION: (0.030, 0.48, 0.0, "yellow"),
        State.DENIED_ERROR: (0.090, 0.78, 0.0, "red"),
        State.SUCCESS: (0.035, 0.54, 0.0, "green"),
    }
    MACCHIATO = {
        "lavender": QColor("#b7bdf8"),
        "sapphire": QColor("#7dc4e4"),
        "blue": QColor("#8aadf4"),
        "peach": QColor("#f5a97f"),
        "yellow": QColor("#eed49f"),
        "red": QColor("#ed8796"),
        "green": QColor("#a6da95"),
    }

    def __init__(self, parent=None, *,
                 size: int = 400,
                 floating: bool = False,
                 line_width: float = 5.0,
                 fill_ratio: float = 0.0,
                 spectrum_radius: float = 110.4,
                 spectrum_sensitivity: float = 1.0,
                 spectrum_smoothing: float = 0.72,
                 spectrum_deformation: float = 18.0):
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
        self.set_spectrum_parameters(
            radius=spectrum_radius,
            sensitivity=spectrum_sensitivity,
            smoothing=spectrum_smoothing,
            deformation=spectrum_deformation)
        self.set_size(size)
        self.setToolTip("Arlo")

        self.levels = [0.0] * 15
        self.smoothed = [0.0] * 15

        self.amplitude = 0.0
        self.phase = 0.0
        self.speaking = False
        self.listening = False
        self.thinking = False
        self.thinking_mix = 0.0
        self.thinking_rotation = 0.0
        self.speech_pulse_enabled = True
        self.speech_scale = 1.0
        self.visual_state = self.State.IDLE
        self._state_mix = 1.0
        self._state_fade = 0.18
        self._state_phase = 0.0
        self._state_rotation = 0.0
        self._state_color = QColor(self.MACCHIATO["lavender"])
        self._target_color = QColor(self._state_color)

        self.click_pulse = 0.0
        self.double_pulse = 0.0

        self._pop_scale = 1.0
        self._pop_animation = QPropertyAnimation(self, b"pop_scale", self)
        self._pop_animation.finished.connect(self._finish_pop)

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

    @Property(float)
    def pop_scale(self):
        return self._pop_scale

    @pop_scale.setter
    def pop_scale(self, value):
        self._pop_scale = max(0.0, float(value))
        self.update()

    def pop_in(self):
        """Show with a centered pop, or reverse an ongoing pop-out."""
        if not self.isVisible():
            self._pop_animation.stop()
            self.pop_scale = 0.0
            self.show()
        self._start_pop(1.0, 300, QEasingCurve.Type.OutBack)

    def pop_out(self):
        """Shrink away before hiding the widget."""
        if self.isVisible():
            self.click_timer.stop()
            self.restore_timer.stop()
            self._start_pop(0.0, 180, QEasingCurve.Type.InBack)

    def _start_pop(self, target, duration, easing):
        animation = self._pop_animation
        if (animation.state() == QAbstractAnimation.State.Running
                and animation.endValue() == target):
            return
        animation.stop()
        animation.setDuration(duration)
        animation.setEasingCurve(easing)
        animation.setStartValue(self.pop_scale)
        animation.setEndValue(target)
        animation.start()

    def _finish_pop(self):
        if self._pop_animation.endValue() == 0.0:
            self.hide()

    def set_thinking(self, thinking: bool):
        self.thinking = bool(thinking)

    def set_visual_state(self, state, *, fade_in=180, fade_out=180):
        """Transition to a deterministic visual state using the app palette."""
        try:
            state = state if isinstance(state, self.State) else self.State(state)
        except (TypeError, ValueError):
            state = self.State.IDLE
        if state == self.visual_state:
            return
        _, _, _, role_name = self.STATE_PROFILES[state]
        self._state_color = QColor(self._target_color)
        self._target_color = QColor(self.MACCHIATO[role_name])
        self.visual_state = state
        self._state_mix = 0.0
        self._state_fade = max(1.0, float(fade_in + fade_out) / 2.0)
        self.update()

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

    def set_spectrum_parameters(self, *, radius=None, sensitivity=None,
                                smoothing=None, deformation=None):
        values = {
            "radius": radius,
            "sensitivity": sensitivity,
            "smoothing": smoothing,
            "deformation": deformation,
        }
        for name, value in values.items():
            if value is None:
                continue
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value)):
                raise ValueError(f"Spectrum {name} must be a finite number")
            if name == "smoothing" and not 0.0 <= value < 1.0:
                raise ValueError("Spectrum smoothing must be from 0 up to 1")
            if name != "smoothing" and value < 0.0:
                raise ValueError(f"Spectrum {name} must not be negative")
            setattr(self, f"spectrum_{name}", float(value))
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
            response = 1.0 - self.spectrum_smoothing
            factor = response if target > current else response * 0.42
            self.smoothed[index] += (target - current) * factor
            if self.smoothed[index] < 0.0005:
                self.smoothed[index] = 0.0

        target = max(self.smoothed)
        factor = (0.55 if target > self.amplitude
                  else 0.12)

        self.amplitude += (target - self.amplitude) * factor
        if self.amplitude < 0.0005:
            self.amplitude = 0.0

        speech_scale_target = 1.0
        if self.listening:
            speech_scale_target = 0.90 + self.amplitude * 0.24
        elif self.speaking and self.speech_pulse_enabled:
            speech_scale_target = 0.93 + self.amplitude * 0.22
        scale_factor = (0.28 if speech_scale_target > self.speech_scale
                        else 0.18)
        self.speech_scale += (speech_scale_target - self.speech_scale) * scale_factor

        speed, target_amplitude, rotation, _ = self.STATE_PROFILES[self.visual_state]
        self._state_mix += (1.0 - self._state_mix) * min(1.0, 16.0 / self._state_fade)
        current = [self._state_color.red(), self._state_color.green(),
                   self._state_color.blue(), self._state_color.alpha()]
        target = [self._target_color.red(), self._target_color.green(),
                  self._target_color.blue(), self._target_color.alpha()]
        self._state_color.setRgb(*[
            round(value + (goal - value) * 0.12)
            for value, goal in zip(current, target)])
        self._state_phase += speed
        self._state_rotation += rotation
        self.phase += (speed + self.amplitude * 0.045)

        self.click_pulse *= 0.88
        self.double_pulse *= 0.93

        if self.click_pulse < 0.001:
            self.click_pulse = 0.0

        if self.double_pulse < 0.001:
            self.double_pulse = 0.0

        target = 1.0 if self.thinking else 0.0

        self.thinking_mix += (target - self.thinking_mix) * 0.085
        if abs(target - self.thinking_mix) < 0.001:
            self.thinking_mix = target

        self.thinking_rotation += 0.090 * self.thinking_mix
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
        painter.setOpacity(min(1.0, self.pop_scale))
        painter.scale(scale * self.speech_scale * self.pop_scale,
                      scale * self.speech_scale * self.pop_scale)
        points = 240
        colors = []
        for index, alpha in enumerate((240, 165)):
            accent = QColor(self._state_color)
            if not accent.isValid():
                accent = QColor(self.MACCHIATO["lavender"])
            color = QColor(accent)
            color.setAlpha(round(alpha * (0.72 + 0.28 * self._state_mix)))
            colors.append(color)

        inner_fill = QColor(self._state_color)

        if not inner_fill.isValid():
            inner_fill = QColor(self.MACCHIATO["lavender"])

        inner_fill.setAlpha(colors[0].alpha())

        if self.visual_state == self.State.IDLE:
            breathing = math.sin(self._state_phase * 0.75) * 1.6
        else:
            breathing = math.sin(self._state_phase * 1.7) * 0.8
        inner_radius = (102.4 * (1.0 - 0.15 * self.thinking_mix)
                        + breathing + self.click_pulse * 1.5
                        + self.double_pulse * 4.0)
        inner_rect = QRectF(-inner_radius, -inner_radius,
                            inner_radius * 2.0, inner_radius * 2.0)

        if self.fill_ratio:
            fill_radius = 102.4 * self.fill_ratio
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(inner_fill)
            painter.drawEllipse(QPointF(0.0, 0.0), fill_radius, fill_radius)

        inner_color = colors[0]
        solid_color = QColor(inner_color)
        solid_color.setAlphaF(inner_color.alphaF() * (1.0 - self.thinking_mix))
        if solid_color.alpha() > 0:
            pen = QPen(solid_color)
            pen.setWidthF(self.line_width / scale)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(inner_rect)

        if self.thinking_mix > 0.001:
            dashed_color = QColor(inner_color)
            dashed_color.setAlphaF(
                inner_color.alphaF() * self.thinking_mix)
            pen = QPen(dashed_color)
            pen.setWidthF(self.line_width / scale)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setDashPattern([5.0, 4.0])
            pen.setDashOffset(self.thinking_rotation)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(inner_rect)

        spectrum_path = QPainterPath()
        band_count = len(self.smoothed)
        band_order = []
        for band in range((band_count + 1) // 2):
            band_order.append(band)
            opposite_band = band_count - 1 - band
            if opposite_band != band:
                band_order.append(opposite_band)
        for index in range(points + 1):
            position = index / points * band_count
            slot = int(position) % band_count
            fraction = position - int(position)
            fraction = fraction * fraction * (3.0 - 2.0 * fraction)
            next_slot = (slot + 1) % band_count
            level = (self.smoothed[band_order[slot]] * (1.0 - fraction)
                     + self.smoothed[band_order[next_slot]] * fraction)
            energy = min(1.0, level * self.spectrum_sensitivity)
            radius = (self.spectrum_radius
                      + energy ** 0.72 * self.spectrum_deformation)
            angle = index / points * math.tau
            point = QPointF(math.cos(angle) * radius,
                            math.sin(angle) * radius)
            if index == 0:
                spectrum_path.moveTo(point)
            else:
                spectrum_path.lineTo(point)
        spectrum_path.closeSubpath()

        pen = QPen(colors[1])
        pen.setWidthF(self.line_width * 0.85 / scale)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(spectrum_path)

        painter.end()

    def move_mascot(self):
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
        self._pop_animation.stop()
        self.pop_scale = 1.0
        self.click_timer.stop()
        self.restore_timer.stop()
        self._drag_origin = None
        self._drag_offset = None
        self._dragging = False
        self._suppress_release_click = False
        if self.floating:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().hideEvent(event)
