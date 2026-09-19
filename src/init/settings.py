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

from PySide6.QtCore import Qt, Signal, Property, QPropertyAnimation
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractButton, QComboBox, QHBoxLayout, QLabel, QListView, QVBoxLayout, QWidget)

from .lang import get_language, tr


class ToggleSwitch(QAbstractButton):
    """Animated toggle for Qt Widgets."""
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(48, 26)

        self._offset = 0.0

        self._animation = QPropertyAnimation(self, b"offset", self)
        self._animation.setDuration(160)

        self.toggled.connect(self._animate)

        self._track_off = QColor("#555965")
        self._track_on = QColor("#7486F5")
        self._thumb_color = QColor("#FFFFFF")

    def get_offset(self) -> float:
        return self._offset

    def set_offset(self, value: float):
        self._offset = value
        self.update()

    offset = Property(float, get_offset, set_offset)

    def get_track_off(self):
        return self._track_off

    def set_track_off(self, color):
        self._track_off = QColor(color)
        self.update()

    trackOff = Property(QColor, get_track_off, set_track_off)

    def get_track_on(self):
        return self._track_on

    def set_track_on(self, color):
        self._track_on = QColor(color)
        self.update()

    trackOn = Property(QColor, get_track_on, set_track_on)

    def get_thumb_color(self):
        return self._thumb_color

    def set_thumb_color(self, color):
        self._thumb_color = QColor(color)
        self.update()

    thumbColor = Property(QColor, get_thumb_color, set_thumb_color)

    def _animate(self, checked: bool):
        self._animation.stop()

        self._animation.setStartValue(self._offset)
        self._animation.setEndValue(1.0 if checked else 0.0)

        self._animation.start()

    def setChecked(self, checked: bool):
        super().setChecked(checked)
        if not self.isVisible():
            self._animation.stop()
            self.set_offset(1.0 if checked else 0.0)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        width = self.width()
        height = self.height()

        margin = 3
        diameter = height - margin * 2
        inactive = self._track_off
        active = self._track_on
        t = self._offset
        track_color = QColor(
            round(inactive.red() + (active.red() - inactive.red()) * t),
            round(inactive.green() + (active.green() - inactive.green()) * t),
            round(inactive.blue() + (active.blue() - inactive.blue()) * t),
        )

        painter.setPen(Qt.NoPen)
        painter.setBrush(track_color)

        painter.drawRoundedRect(
            0, 0, width, height,
            height / 2, height / 2,
        )

        x = margin + (width - diameter - margin * 2) * t
        painter.setBrush(self._thumb_color)
        painter.drawEllipse(
            round(x),
            margin,
            diameter,
            diameter)

        painter.end()


class SettingsView(QWidget):
    """Desktop subtitle and interface language preferences."""
    subtitles_changed = Signal(bool)
    language_changed = Signal(str)

    def __init__(self, subtitles_enabled: bool, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 12, 32, 20)
        layout.setSpacing(24)

        self.title = QLabel()
        self.title.setObjectName("settingsTitle")
        layout.addWidget(self.title)

        self.subtitle_label = QLabel()
        self.subtitle_label.setObjectName("muted")
        self.subtitles_switch = ToggleSwitch()
        self.subtitles_switch.setChecked(subtitles_enabled)
        self.subtitle_label.setBuddy(self.subtitles_switch)
        subtitle_row = QHBoxLayout()
        subtitle_row.addWidget(self.subtitle_label)
        subtitle_row.addStretch()
        subtitle_row.addWidget(self.subtitles_switch)
        layout.addLayout(subtitle_row)

        self.language_label = QLabel()
        self.language_label.setObjectName("muted")
        self.language_dropdown = QComboBox()
        self.language_dropdown.setObjectName("languageDropdown")
        arrow = QLabel("\uf0d7", self.language_dropdown)
        arrow.setObjectName("languageDropdownArrow")
        arrow.setAttribute(Qt.WA_TransparentForMouseEvents)
        arrow.setAlignment(Qt.AlignCenter)
        arrow.setFixedWidth(28)
        arrow_layout = QHBoxLayout(self.language_dropdown)
        arrow_layout.setContentsMargins(0, 0, 1, 0)
        arrow_layout.addStretch()
        arrow_layout.addWidget(arrow)
        language_options = QListView(self.language_dropdown)
        language_options.setMouseTracking(True)
        self.language_dropdown.setView(language_options)
        self.language_dropdown.addItem("English", "english")
        self.language_dropdown.addItem("Español", "spanish")
        self.language_dropdown.setMinimumWidth(180)
        self.language_label.setBuddy(self.language_dropdown)
        language_row = QHBoxLayout()
        language_row.addWidget(self.language_label)
        language_row.addStretch()
        language_row.addWidget(self.language_dropdown)
        layout.addLayout(language_row)
        layout.addStretch()

        self.refresh_language()
        self.subtitles_switch.toggled.connect(self.subtitles_changed.emit)
        self.language_dropdown.currentIndexChanged.connect(
            lambda _: self.language_changed.emit(self.language_dropdown.currentData()))

    def refresh_language(self):
        self.language_dropdown.blockSignals(True)
        self.language_dropdown.setCurrentIndex(
            self.language_dropdown.findData(get_language()))
        self.language_dropdown.blockSignals(False)
        self.title.setText(tr("ui.settings"))
        self.subtitle_label.setText(tr("ui.subtitles"))
        self.subtitles_switch.setAccessibleName(tr("ui.subtitles"))
        self.subtitles_switch.setToolTip(tr("ui.subtitles_hint"))
        self.language_label.setText(tr("ui.language"))
        self.language_dropdown.setAccessibleName(tr("ui.language"))
        self.language_dropdown.setToolTip(tr("ui.language_hint"))
