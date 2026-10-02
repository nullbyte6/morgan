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

import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QFileInfo, QSize, Qt, Signal, Property, QPropertyAnimation, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QImage, QIntValidator, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QComboBox, QFileDialog, QFileIconProvider, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QListView, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from .choice_dialog import ChoiceDialog
from .config import CONTEXT_LENGTH_RANGE, load_config, save_config
from .identity import get_assistant_name
from .lang import get_language, tr
from .ollama_service import ollama_executable, restart_ollama
from .theme import current_theme, discover_themes, on_theme_changed, seed_user_themes, select_theme
from .voice_profiles import available_voices, selected_voice, select_voice, VOICE_NAMES


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

        theme = current_theme()
        self._track_off = theme.color("toggle_track_off")
        self._track_on = theme.color("toggle_track_on")
        self._thumb_color = theme.color("toggle_thumb")

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


def ollama_icon(color: QColor) -> QIcon:
    """The Ollama llama from the installed program, redrawn in the given color; empty when Ollama is missing."""
    executable = ollama_executable()
    if executable is None:
        return QIcon()
    artwork = executable.with_name("app.ico")
    source = QIcon(str(artwork)) if artwork.is_file() else QFileIconProvider().icon(QFileInfo(str(executable)))
    image = source.pixmap(128, 128).toImage().convertToFormat(QImage.Format.Format_ARGB32)
    rgb = color.rgb() & 0xFFFFFF
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = image.pixel(x, y)
            gray = (((pixel >> 16) & 255) * 299 + ((pixel >> 8) & 255) * 587 + (pixel & 255) * 114) // 1000
            image.setPixel(x, y, ((pixel >> 24) & 255) * (255 - gray) // 255 << 24 | rgb)
    return QIcon(QPixmap.fromImage(image))


class ThemeDropdown(QComboBox):
    """Combo box that asks for a fresh theme list before opening."""
    popup_requested = Signal()

    def showPopup(self):
        self.popup_requested.emit()
        super().showPopup()


class SettingsView(QWidget):
    """Desktop subtitle and interface language preferences."""
    subtitles_changed = Signal(bool)
    orb_pulse_changed = Signal(bool)
    ephemeral_steps_changed = Signal(bool)
    mute_changed = Signal(bool)
    language_changed = Signal(str)
    model_changed = Signal(str)
    update_requested = Signal()
    ollama_restarted = Signal(str, int)
    ACTION_COLUMNS = 3

    def __init__(self, subtitles_enabled: bool,
                 orb_pulse_enabled: bool, parent=None, *, muted=False, ephemeral_steps_enabled=True):
        super().__init__(parent)
        self.setObjectName("settingsPage")
        content = QWidget()
        content.setObjectName("settingsPage")
        self.scroll = QScrollArea()
        self.scroll.setObjectName("settingsScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.scroll)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(32, 12, 32, 20)
        layout.setSpacing(24)

        self.mute_label = QLabel()
        self.mute_label.setObjectName("muted")
        self.mute_switch = ToggleSwitch()
        self.mute_switch.setChecked(muted)
        self.mute_label.setBuddy(self.mute_switch)
        mute_row = QHBoxLayout()
        mute_row.addWidget(self.mute_label)
        mute_row.addStretch()
        mute_row.addWidget(self.mute_switch)
        layout.addLayout(mute_row)
        self.mute_switch.toggled.connect(self.mute_changed.emit)

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

        self.orb_pulse_label = QLabel()
        self.orb_pulse_label.setObjectName("muted")
        self.orb_pulse_switch = ToggleSwitch()
        self.orb_pulse_switch.setChecked(orb_pulse_enabled)
        self.orb_pulse_label.setBuddy(self.orb_pulse_switch)
        orb_pulse_row = QHBoxLayout()
        orb_pulse_row.addWidget(self.orb_pulse_label)
        orb_pulse_row.addStretch()
        orb_pulse_row.addWidget(self.orb_pulse_switch)
        layout.addLayout(orb_pulse_row)

        self.ephemeral_steps_label = QLabel()
        self.ephemeral_steps_label.setObjectName("muted")
        self.ephemeral_steps_switch = ToggleSwitch()
        self.ephemeral_steps_switch.setChecked(ephemeral_steps_enabled)
        self.ephemeral_steps_label.setBuddy(self.ephemeral_steps_switch)
        ephemeral_steps_row = QHBoxLayout()
        ephemeral_steps_row.addWidget(self.ephemeral_steps_label)
        ephemeral_steps_row.addStretch()
        ephemeral_steps_row.addWidget(self.ephemeral_steps_switch)
        layout.addLayout(ephemeral_steps_row)

        self.language_label = QLabel()
        self.language_label.setObjectName("muted")
        self.language_dropdown = QComboBox()
        self.language_dropdown.setObjectName("languageDropdown")

        self.language_dropdown.view().setAutoFillBackground(True)
        self.language_dropdown.view().viewport().setAutoFillBackground(True)

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
        self.language_dropdown.addItem("中文", "chinese")
        self.language_dropdown.setMinimumWidth(90)
        self.language_label.setBuddy(self.language_dropdown)
        language_row = QHBoxLayout()
        language_row.addWidget(self.language_label)
        language_row.addStretch()
        language_row.addWidget(self.language_dropdown)
        layout.addLayout(language_row)

        self.refresh_language()
        self.subtitles_switch.toggled.connect(self.subtitles_changed.emit)
        self.orb_pulse_switch.toggled.connect(self.orb_pulse_changed.emit)
        self.ephemeral_steps_switch.toggled.connect(self.ephemeral_steps_changed.emit)
        self.language_dropdown.currentIndexChanged.connect(
            lambda: self.language_changed.emit(self.language_dropdown.currentData()))

        self.model_dropdown = QComboBox()
        self.model_dropdown.setObjectName("modelDropdown")
        self.model_dropdown.view().setAutoFillBackground(True)
        self.model_dropdown.view().viewport().setAutoFillBackground(True)

        arrow = QLabel("\uf0d7", self.model_dropdown)
        arrow.setObjectName("languageDropdownArrow")
        arrow.setAttribute(Qt.WA_TransparentForMouseEvents)
        arrow.setAlignment(Qt.AlignCenter)
        arrow.setFixedWidth(28)
        arrow_layout = QHBoxLayout(self.model_dropdown)
        arrow_layout.setContentsMargins(0, 0, 1, 0)
        arrow_layout.addStretch()
        arrow_layout.addWidget(arrow)

        self.model_label = QLabel()
        self.model_label.setObjectName("muted")
        model_options = QListView(self.model_dropdown)
        model_options.setMouseTracking(True)
        self.model_dropdown.setView(model_options)

        self.model_dropdown.setMinimumWidth(90)
        self.model_label.setBuddy(self.model_dropdown)
        language_row = QHBoxLayout()
        language_row.addWidget(self.model_label)
        language_row.addStretch()
        language_row.addWidget(self.model_dropdown)
        layout.addLayout(language_row)

        self.theme_label = QLabel()
        self.theme_label.setObjectName("muted")
        self.theme_dropdown = ThemeDropdown()
        self.theme_dropdown.setObjectName("themeDropdown")
        self.theme_dropdown.view().setAutoFillBackground(True)
        self.theme_dropdown.view().viewport().setAutoFillBackground(True)

        arrow = QLabel("\uf0d7", self.theme_dropdown)
        arrow.setObjectName("languageDropdownArrow")
        arrow.setAttribute(Qt.WA_TransparentForMouseEvents)
        arrow.setAlignment(Qt.AlignCenter)
        arrow.setFixedWidth(28)
        arrow_layout = QHBoxLayout(self.theme_dropdown)
        arrow_layout.setContentsMargins(0, 0, 1, 0)
        arrow_layout.addStretch()
        arrow_layout.addWidget(arrow)

        theme_options = QListView(self.theme_dropdown)
        theme_options.setMouseTracking(True)
        self.theme_dropdown.setView(theme_options)
        self.theme_dropdown.setMaxVisibleItems(4)
        self.theme_dropdown.setMinimumWidth(180)
        self.theme_label.setBuddy(self.theme_dropdown)
        theme_row = QHBoxLayout()
        theme_row.addWidget(self.theme_label)
        theme_row.addStretch()
        theme_row.addWidget(self.theme_dropdown)
        layout.addLayout(theme_row)

        self.context_label = QLabel()
        self.context_label.setObjectName("muted")
        self.context_input = QLineEdit()
        self.context_input.setObjectName("contextLengthInput")
        self.context_input.setValidator(QIntValidator(0, CONTEXT_LENGTH_RANGE[1], self.context_input))
        self.context_input.setAlignment(Qt.AlignRight)
        self.context_input.setFixedWidth(180)
        self.context_input.setText(str(load_config()["context_length"]))
        self.context_label.setBuddy(self.context_input)
        self.ollama_button = QPushButton()
        self.ollama_button.setObjectName("ollamaButton")
        self.ollama_button.setCursor(Qt.PointingHandCursor)
        self.context_input.ensurePolished()
        height = max(self.context_input.sizeHint().height(), self.context_input.minimumSizeHint().height())
        self.ollama_button.setFixedSize(height, height)
        self.ollama_button.setIconSize(QSize(height - 12, height - 12))
        context_row = QHBoxLayout()
        context_row.setSpacing(8)
        context_row.addWidget(self.context_label)
        context_row.addStretch()
        context_row.addWidget(self.ollama_button)
        context_row.addWidget(self.context_input)
        layout.addLayout(context_row)
        self.context_input.editingFinished.connect(self.change_context_length)
        self.ollama_button.clicked.connect(self.restart_ollama)
        self.ollama_restarted.connect(self.finish_restart_ollama)
        self.refresh_ollama_icon()

        layout.addStretch()

        self.action_grid = QGridLayout()
        self.action_grid.setSpacing(12)
        for column in range(self.ACTION_COLUMNS):
            self.action_grid.setColumnStretch(column, 1)
        layout.addLayout(self.action_grid)

        self.themes_folder_button = self.add_action_button("themesFolderButton")
        self.update_button = self.add_action_button("themesFolderButton")
        self.backup_button = self.add_action_button("themesFolderButton")
        self.restore_button = self.add_action_button("themesFolderButton")
        self.remove_memories_button = self.add_action_button("removeMemoriesButton")
        self.remove_markdowns_button = self.add_action_button("removeMemoriesButton")
        self.update_button.clicked.connect(self.update_requested.emit)
        self.backup_button.clicked.connect(self.backup_data)
        self.restore_button.clicked.connect(self.restore_data)
        self.remove_memories_button.clicked.connect(self.remove_memories)
        self.remove_markdowns_button.clicked.connect(self.remove_markdowns)
        self.dialog = ChoiceDialog(self)

        for dropdown in (self.language_dropdown, self.model_dropdown, self.theme_dropdown):
            dropdown.installEventFilter(self)

        self.theme_dropdown.popup_requested.connect(self.refresh_themes)
        self.theme_dropdown.activated.connect(self.change_theme)
        self.themes_folder_button.clicked.connect(self.open_themes_folder)
        on_theme_changed(self.apply_theme)
        self.refresh_themes()

        self.model_dropdown.activated.connect(self.change_voice)
        self.refresh_voices()
        self.refresh_language()
        self.voice_timer = QTimer(self)
        self.voice_timer.setInterval(1000)
        self.voice_timer.timeout.connect(self.refresh_voices)
        self.voice_timer.start()

    def eventFilter(self, watched, event):
        if isinstance(watched, QComboBox) and event.type() == QEvent.Type.Wheel:
            QApplication.sendEvent(self.scroll.viewport(), event)
            return True
        return super().eventFilter(watched, event)

    def add_action_button(self, object_name: str) -> QPushButton:
        """Place a new button in the next free cell of the action grid."""
        button = QPushButton()
        button.setObjectName(object_name)
        button.setCursor(Qt.PointingHandCursor)
        button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        index = self.action_grid.count()
        self.action_grid.addWidget(button, index // self.ACTION_COLUMNS, index % self.ACTION_COLUMNS)
        return button

    def refresh_themes(self):
        current = current_theme()
        themes = discover_themes()
        if current.id not in {theme.id for theme in themes}:
            themes.append(current)
        items = [(theme.name, theme.id) for theme in themes]
        self.theme_dropdown.blockSignals(True)
        try:
            existing = [(self.theme_dropdown.itemText(i), self.theme_dropdown.itemData(i))
                        for i in range(self.theme_dropdown.count())]
            if existing != items:
                self.theme_dropdown.clear()
                for name, theme_id in items:
                    self.theme_dropdown.addItem(name, theme_id)
            self.theme_dropdown.setCurrentIndex(self.theme_dropdown.findData(current.id))
        finally:
            self.theme_dropdown.blockSignals(False)

    def change_theme(self, index):
        theme_id = self.theme_dropdown.itemData(index)
        if theme_id:
            select_theme(theme_id)

    def apply_theme(self, theme):
        self.refresh_themes()
        self.refresh_ollama_icon()

    def refresh_ollama_icon(self):
        icon = ollama_icon(current_theme().color("text"))
        self.ollama_button.setIcon(icon)
        self.ollama_button.setText("" if not icon.isNull() else "\u21bb")

    def change_context_length(self):
        minimum, maximum = CONTEXT_LENGTH_RANGE
        config = load_config()
        text = self.context_input.text().strip()
        if text.isdigit() and minimum <= int(text) <= maximum:
            value = int(text)
            if value != config["context_length"]:
                try:
                    save_config({**config, "context_length": value})
                except (OSError, ValueError) as error:
                    self.dialog.notify(tr("ui.context_length"), tr("ui.error", error=error))
                    value = config["context_length"]
        else:
            value = config["context_length"]
            self.dialog.notify(
                tr("ui.context_length"),
                tr("ui.context_length_hint", minimum=minimum, maximum=maximum, name=get_assistant_name()))
        self.context_input.setText(str(value))

    def open_themes_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(seed_user_themes())))

    def backup_data(self):
        from .memory.integration import backup_data
        path, _filter = QFileDialog.getSaveFileName(
            self, tr("ui.backup_data"),
            str(Path.home() / f"{get_assistant_name()}-backup-{datetime.now():%Y-%m-%d}.zip"), "Zip (*.zip)")
        if not path:
            return
        try:
            counts = backup_data(path)
        except Exception as error:
            self.dialog.notify(tr("ui.backup_data"), tr("ui.error", error=error))
            return
        self.dialog.notify(tr("ui.backup_data"), tr("ui.backup_data_done", path=path, **counts))

    def restore_data(self):
        path, _filter = QFileDialog.getOpenFileName(self, tr("ui.restore_data"), str(Path.home()), "Zip (*.zip)")
        if not path:
            return
        self.dialog.confirm(
            tr("ui.restore_data"), tr("ui.restore_data_confirm"), lambda: self.run_restore(path))

    def run_restore(self, path):
        from .memory.integration import restore_data
        from .nova.tools import refresh_store
        try:
            counts = restore_data(path)
        except Exception as error:
            self.dialog.notify(tr("ui.restore_data"), tr("ui.error", error=error))
            return
        refresh_store()
        self.dialog.notify(tr("ui.restore_data"), tr("ui.restore_data_done", **counts))

    def restart_ollama(self):
        self.dialog.confirm(
            tr("ui.restart_ollama"), tr("ui.restart_ollama_confirm", context_length=load_config()["context_length"]),
            self.run_restart_ollama, danger=False)

    def run_restart_ollama(self):
        length = load_config()["context_length"]
        self.ollama_button.setEnabled(False)

        def work():
            try:
                restart_ollama(length)
                error = ""
            except Exception as failure:
                error = str(failure) or type(failure).__name__
            try:
                self.ollama_restarted.emit(error, length)
            except RuntimeError:
                pass

        threading.Thread(target=work, name="ollama-restart", daemon=True).start()

    def finish_restart_ollama(self, error: str, length: int):
        self.ollama_button.setEnabled(True)
        if error:
            self.dialog.notify(tr("ui.restart_ollama"), tr("ui.error", error=error))
        else:
            self.dialog.notify(tr("ui.restart_ollama"), tr("ui.restart_ollama_done", context_length=length))

    def remove_memories(self):
        self.dialog.confirm(tr("ui.remove_memories"), tr("ui.remove_memories_confirm"), self.run_remove_memories)

    def run_remove_memories(self):
        from .memory.integration import clear_memories
        try:
            clear_memories()
        except Exception as error:
            self.dialog.notify(tr("ui.remove_memories"), tr("ui.error", error=error))
            return
        self.dialog.notify(tr("ui.remove_memories"), tr("ui.remove_memories_done"))

    def remove_markdowns(self):
        self.dialog.confirm(tr("ui.remove_markdowns"), tr("ui.remove_markdowns_confirm"), self.run_remove_markdowns)

    def run_remove_markdowns(self):
        from .session_log import clear_logs
        try:
            clear_logs()
        except Exception as error:
            self.dialog.notify(tr("ui.remove_markdowns"), tr("ui.error", error=error))
            return
        self.dialog.notify(tr("ui.remove_markdowns"), tr("ui.remove_markdowns_done"))

    def refresh_voices(self):
        voices = available_voices()
        names = [path.name for path in voices]
        selected = selected_voice()
        self.model_dropdown.blockSignals(True)
        try:
            current = [self.model_dropdown.itemData(i)
                       for i in range(self.model_dropdown.count())]
            if current != names:
                self.model_dropdown.clear()
                for path in voices:
                    label = VOICE_NAMES.get(path.name, path.stem)
                    self.model_dropdown.addItem(label, path.name)
            self.model_dropdown.setCurrentIndex(
                self.model_dropdown.findData(selected.name) if selected else -1)
            self.model_dropdown.setEnabled(bool(voices))
        finally:
            self.model_dropdown.blockSignals(False)

    def change_voice(self, index):
        name = self.model_dropdown.itemData(index)
        if not name:
            return
        try:
            select_voice(name)
        except (OSError, ValueError) as error:
            self.dialog.notify(tr("ui.voice"), str(error))
            self.refresh_voices()
            return
        self.model_changed.emit(name)

    def refresh_language(self):
        self.mute_label.setText(tr("ui.mute"))
        self.mute_switch.setAccessibleName(tr("ui.mute"))
        self.mute_switch.setToolTip(tr("ui.mute_hint"))
        self.language_dropdown.blockSignals(True)
        self.language_dropdown.setCurrentIndex(
            self.language_dropdown.findData(get_language()))
        self.language_dropdown.blockSignals(False)
        self.subtitle_label.setText(tr("ui.subtitles"))
        self.subtitles_switch.setAccessibleName(tr("ui.subtitles"))
        self.subtitles_switch.setToolTip(tr("ui.subtitles_hint"))
        self.orb_pulse_label.setText(tr("ui.orb_speech_pulse"))
        self.orb_pulse_switch.setAccessibleName(tr("ui.orb_speech_pulse"))
        self.orb_pulse_switch.setToolTip(tr("ui.orb_speech_pulse_hint"))
        self.ephemeral_steps_label.setText(tr("ui.ephemeral_steps"))
        self.ephemeral_steps_switch.setAccessibleName(tr("ui.ephemeral_steps"))
        self.ephemeral_steps_switch.setToolTip(tr("ui.ephemeral_steps_hint"))
        self.language_label.setText(tr("ui.language"))
        self.language_dropdown.setAccessibleName(tr("ui.language"))
        self.language_dropdown.setToolTip(tr("ui.language_hint"))
        if hasattr(self, "model_label"):
            self.model_label.setText(tr("ui.voice"))
            self.model_dropdown.setAccessibleName(tr("ui.voice"))
            self.model_dropdown.setToolTip(tr("ui.voice_hint"))
        if hasattr(self, "theme_label"):
            self.theme_label.setText(tr("ui.theme"))
            self.theme_dropdown.setAccessibleName(tr("ui.theme"))
            self.theme_dropdown.setToolTip(tr("ui.theme_hint"))
            self.themes_folder_button.setText(tr("ui.open_themes_folder"))
        if hasattr(self, "ollama_button"):
            self.ollama_button.setAccessibleName(tr("ui.restart_ollama"))
            self.ollama_button.setToolTip(tr("ui.restart_ollama_hint"))
        if hasattr(self, "context_label"):
            self.context_label.setText(tr("ui.context_length"))
            self.context_input.setAccessibleName(tr("ui.context_length"))
            self.context_input.setToolTip(tr(
                "ui.context_length_hint", minimum=CONTEXT_LENGTH_RANGE[0],
                maximum=CONTEXT_LENGTH_RANGE[1], name=get_assistant_name()))
        if hasattr(self, "update_button"):
            self.update_button.setText(tr("ui.check_updates"))
            self.update_button.setToolTip(tr("ui.check_updates_hint"))
        if hasattr(self, "backup_button"):
            self.backup_button.setText(tr("ui.backup_data"))
            self.backup_button.setToolTip(tr("ui.backup_data_hint"))
            self.restore_button.setText(tr("ui.restore_data"))
            self.restore_button.setToolTip(tr("ui.restore_data_hint"))
        if hasattr(self, "remove_memories_button"):
            self.remove_memories_button.setText(tr("ui.remove_memories"))
            self.remove_memories_button.setToolTip(tr("ui.remove_memories_hint"))
        if hasattr(self, "remove_markdowns_button"):
            self.remove_markdowns_button.setText(tr("ui.remove_markdowns"))
            self.remove_markdowns_button.setToolTip(tr("ui.remove_markdowns_hint"))
