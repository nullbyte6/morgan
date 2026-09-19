#!/usr/bin/env python3
#
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

"""Arlo desktop interface using PySide6."""
import asyncio
import html
import json
import math
import random
import re
import sys
import threading
from getpass import getuser
from pathlib import Path

from PySide6.QtCore import (
    Qt, QObject, QThread, QTimer, Signal, Slot,
    Property, QPropertyAnimation, QSettings)

from PySide6.QtGui import (
    QColor, QFont, QFontDatabase,
    QIcon, QPainter, QPainterPath, QPen)

from PySide6.QtWidgets import (
    QApplication, QAbstractButton, QFrame, QHBoxLayout,
    QLabel, QMainWindow, QPushButton, QSizePolicy,
    QTextEdit, QVBoxLayout, QWidget, QMessageBox,
    QPlainTextEdit, QStackedWidget)

from agent import Assistant
from src.init.commands import execute_command, set_confirmation_handler
from src.init.config import load_dev_file
from src.init.lang import get_language, set_language, tr
from src.init.session_log import SessionLog
from src.init.terminal import spectrum_levels
from src.init.logs import LogView

class ChatInput(QTextEdit):
    submitted = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.max_lines = 6
        self.setAcceptRichText(False)
        self.document().setDocumentMargin(0)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.document().documentLayout().documentSizeChanged.connect(
            self.adjust_height)
        self.adjust_height()

    def adjust_height(self, *_):
        line_height = self.fontMetrics().lineSpacing()
        content_height = self.document().size().height()
        max_height = self.max_lines * line_height

        height = max(line_height, min(max_height, int(content_height)))
        self.setFixedHeight(height)

        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarAsNeeded if content_height > max_height
            else Qt.ScrollBarAlwaysOff
        )

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return,
                           Qt.Key_Enter) and not event.modifiers() & Qt.ShiftModifier:
            event.accept()
            self.submitted.emit()
            return

        super().keyPressEvent(event)


class AudioVisualizer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(100)
        self.setMinimumWidth(300)

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

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        width = self.width()
        height = self.height()
        center = height / 2

        colors = (
            QColor(245, 247, 255, 240),
            QColor(165, 181, 255, 150),
            QColor(116, 133, 240, 95),
            QColor(96, 113, 205, 55))

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


class ToggleSwitch(QAbstractButton):
    """Interruptor animado para Qt Widgets."""

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


class AssistantWorker(QObject):
    chunk = Signal(int, str)
    audio = Signal(int, object)
    speaking = Signal(int, bool)
    finished = Signal(str)
    failed = Signal(str)
    ready = Signal()
    confirmation_requested = Signal(int, str)

    def __init__(self):
        super().__init__()
        self.assistant = Assistant()
        self.history = []
        self.session = SessionLog()
        self.confirmation_event = threading.Event()
        self.confirmation_answer = False
        self.cancel_event = threading.Event()
        self.command_reply = False
        self.event_loop = None

    @Slot()
    def initialize(self):
        try:
            self.event_loop = asyncio.new_event_loop()
            self.assistant._initialize_runtime()
            self.ready.emit()
        except Exception as error:
            self.failed.emit(str(error))

    @Slot(int, str)
    def ask(self, turn_id, prompt):
        try:
            cancel_event = self.cancel_event
            set_confirmation_handler(
                lambda message: self.confirm_command(message, cancel_event,
                                                     turn_id))
            self.command_reply = False
            if cancel_event.is_set():
                self.finished.emit("")
                return
            privacy_result = self.session.handle_command(prompt)
            if privacy_result is not None:
                self.finished.emit(str(privacy_result))
                return

            self.session.write(self.assistant.username, prompt)

            if prompt.casefold().startswith("pwsh:"):
                self.command_reply = True
                command = prompt[5:].strip()
                raw_result = execute_command(command)
                data = json.loads(raw_result)

                output = data.get("stdout", "")
                error = data.get("stderr", "")

                reply = tr("command.result",
                           status=tr("command.status." + data["status"]),
                           code=data.get("exit_code", "—"), output=output)

                if error:
                    reply += tr("command.stderr", error=error)

                if data["status"] == "error":
                    reply += f"\n\n{data.get('error', '')}"

                self.session.write(self.assistant.name, reply)
                self.finished.emit(reply)
                return

            reply, self.history = self.assistant.run_desktop_turn(
                prompt,
                self.history,
                on_chunk=lambda chunk: self.chunk.emit(turn_id, chunk),
                on_audio=lambda samples, rate: self.report_audio(turn_id,
                                                                 samples, rate),
                on_speaking=lambda speaking: self.speaking.emit(turn_id,
                                                                speaking),
                cancel_event=cancel_event,
                event_loop=self.event_loop)

            if reply:
                self.session.write(self.assistant.name, reply)

            self.finished.emit(reply)

        except Exception as error:
            cause = error.__cause__
            message = tr("ui.error_detail", error=error,
                         cause=cause) if cause is not None else str(
                error)
            self.session.write("System", message)
            self.failed.emit(message)

    def report_audio(self, turn_id, samples, sample_rate):
        if not self.cancel_event.is_set():
            self.audio.emit(turn_id,
                            spectrum_levels(samples, sample_rate).tolist())

    def interrupt(self):
        self.cancel_event.set()
        self.resolve_confirmation(False)

    @Slot()
    def shutdown(self):
        if self.assistant.voice is not None:
            self.assistant.voice.close()
        if self.event_loop is not None:
            self.event_loop.close()

    def confirm_command(self, message: str, cancel_event=None,
                        turn_id=0) -> bool:
        cancel_event = self.cancel_event if cancel_event is None else cancel_event
        if cancel_event.is_set():
            return False
        self.confirmation_answer = False
        self.confirmation_event.clear()
        if cancel_event.is_set():
            return False
        self.confirmation_requested.emit(turn_id, message)
        while not self.confirmation_event.wait(0.05):
            if cancel_event.is_set():
                return False
        return self.confirmation_answer and not cancel_event.is_set()

    def resolve_confirmation(self, accepted: bool):
        self.confirmation_answer = accepted
        self.confirmation_event.set()


class ArloWindow(QMainWindow):
    request = Signal(int, str)
    username = getuser().capitalize()

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"ARLO {load_dev_file()["version"]}")
        icon_path = (Path(__file__).resolve().parent /
                     "assets" / "pwsh.ico")
        self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(900, 720)
        self.setMinimumSize(600, 480)

        self.chat_button = QPushButton("󰭹")
        self.logs_button = QPushButton("󰋚")
        self.settings_button = QPushButton("")
        self.send = QPushButton("")
        self.input = ChatInput()
        self.status = QLabel()
        self.command_output = QPlainTextEdit()
        self.active_language = None
        self.pages = QStackedWidget()
        self.greeting_key = f"greeting.{random.randrange(6)}"
        self.subtitles = QLabel(self.startup_greeting)
        self.subtitle_label = QLabel()
        self.language_switch = ToggleSwitch()
        self.language_label = QLabel()
        self.subtitles_switch = ToggleSwitch()
        self.hero = QLabel(Assistant().banner.rstrip("\n"))
        self.meter = AudioVisualizer()
        self.worker = AssistantWorker()
        self.thread = QThread(self)

        self.log_dir = Path.home() / ".arlo" / "log"
        self.log_view = LogView(self.log_dir, self)

        self.busy = False
        self.ready = False
        self.speaking = False
        self.stopping = False
        self.pending_prompt = None
        self.turn_id = 0
        self.status_key = "status.waking"
        self.showing_greeting = True
        self.current_reply = None
        self.subtitle_text = ""

        self.settings = QSettings("ARLO", "desktop")
        self.build_ui()
        self.build_worker()
        self.set_status("status.waking")
        self.language_timer = QTimer(self)
        self.language_timer.setInterval(500)
        self.language_timer.timeout.connect(self.refresh_language)
        self.language_timer.start()


    def build_ui(self):
        container = QWidget()
        container.setObjectName("windowContainer")
        self.setCentralWidget(container)

        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        navigation = QHBoxLayout()
        navigation.setContentsMargins(20, 8, 20, 0)
        navigation.setSpacing(8)

        self.settings_button.setObjectName("settingsNav")
        self.settings_button.setCheckable(True)
        self.settings_button.setChecked(True)
        self.settings_button.setFixedSize(48, 48)
        self.settings_button.setToolTip(tr("ui.settings"))

        self.chat_button.setObjectName("chatNav")
        self.chat_button.setCheckable(True)
        self.chat_button.setChecked(True)
        self.chat_button.setFixedSize(48, 48)
        self.chat_button.setToolTip("Arlo")

        self.logs_button.setObjectName("logsNav")
        self.logs_button.setCheckable(True)
        self.logs_button.setFixedSize(48, 48)
        self.logs_button.setToolTip("Logs")

        navigation.addWidget(self.settings_button)
        navigation.addWidget(self.chat_button)
        navigation.addWidget(self.logs_button)
        navigation.addStretch()

        container_layout.addLayout(navigation)
        self.pages.setObjectName("mainPages")
        container_layout.addWidget(self.pages, 1)

        root = QWidget()
        root.setObjectName("root")

        main = QVBoxLayout(root)
        main.setContentsMargins(20, 12, 20, 20)
        main.setSpacing(16)

        header = QHBoxLayout()
        header.addStretch()
        switches = QVBoxLayout()

        label_spacing: int = 200
        subtitle_row = QHBoxLayout()

        self.subtitle_label.setObjectName("muted")
        self.subtitle_label.setFixedWidth(label_spacing)

        subtitle_row.setSpacing(8)
        self.subtitle_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        subtitle_row.addWidget(self.subtitle_label)
        enabled = self.settings.value("subtitles", True, type=bool)

        self.subtitles_switch.setChecked(enabled)
        self.subtitles_switch.toggled.connect(self.toggle_subtitles)
        subtitle_row.addWidget(self.subtitles_switch)
        switches.addLayout(subtitle_row)
        language_row = QHBoxLayout()

        self.language_label.setObjectName("muted")
        self.language_label.setFixedWidth(label_spacing)

        language_row.setSpacing(8)
        self.language_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        language_row.addWidget(self.language_label)
        self.language_switch.setChecked(get_language() == "spanish")
        self.language_switch.toggled.connect(self.toggle_language)
        language_row.addWidget(self.language_switch)

        switches.addLayout(language_row)
        header.addLayout(switches)
        main.addLayout(header)

        banner_group = QVBoxLayout()
        banner_group.setSpacing(16)
        banner_group.setAlignment(Qt.AlignCenter)

        self.hero.setObjectName("hero")
        self.hero.setTextFormat(Qt.PlainText)
        self.hero.setAlignment(Qt.AlignCenter)
        self.hero.setWordWrap(False)
        self.hero.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        banner_group.addWidget(self.hero)

        banner_group.addWidget(self.meter)
        main.addLayout(banner_group, 1)

        self.subtitles.setObjectName("subtitles")
        self.subtitles.setAlignment(Qt.AlignCenter)
        self.subtitles.setWordWrap(True)
        self.subtitles.setTextFormat(Qt.RichText)
        self.subtitles.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.subtitles.setFixedHeight(90)
        self.subtitles.setVisible(self.subtitles_switch.isChecked())
        main.addWidget(self.subtitles)

        self.status.setObjectName("status")
        self.status.setAlignment(Qt.AlignCenter)
        main.addWidget(self.status)

        self.command_output.setObjectName("commandOutput")
        self.command_output.setReadOnly(True)
        self.command_output.setMinimumHeight(110)
        self.command_output.setMaximumHeight(220)
        self.command_output.hide()
        main.addWidget(self.command_output)

        composer = QHBoxLayout()
        composer.setSpacing(12)
        composer.setAlignment(Qt.AlignBottom)

        input_frame = QFrame()
        input_frame.setObjectName("inputFrame")
        input_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        input_frame.setMaximumWidth(600)

        input_layout = QVBoxLayout(input_frame)
        input_layout.setContentsMargins(16, 0, 16, 0)
        input_layout.setSpacing(0)

        self.input.submitted.connect(self.send_message)
        input_layout.addWidget(self.input, 0, Qt.AlignVCenter)
        input_frame.setMinimumHeight(48)

        composer.addStretch()
        composer.addWidget(input_frame, 1)

        self.send.setObjectName("send")
        self.send.setFixedSize(48, 48)
        self.send.clicked.connect(self.on_send_clicked)
        composer.addWidget(self.send, 0, Qt.AlignVCenter)
        composer.addStretch()
        main.addLayout(composer)

        self.pages.addWidget(root)
        self.pages.addWidget(self.log_view)
        self.pages.addWidget(self.settings_view)
        self.chat_button.clicked.connect(lambda: self.show_page(0))
        self.logs_button.clicked.connect(lambda: self.show_page(1))
        self.pages.setCurrentIndex(0)


        self.set_enabled(False)
        self.load_stylesheet()
        self.refresh_language()


    def show_page(self, index: int):
        self.pages.setCurrentIndex(index)
        self.chat_button.setChecked(index == 0)
        self.logs_button.setChecked(index == 1)

        if index == 0 and self.ready:
            self.input.setFocus()


    def load_stylesheet(self):
        stylesheet_path = (
                    Path(__file__).resolve().parent / "assets" / "arlo.qss")
        stylesheet = stylesheet_path.read_text(encoding="utf-8")
        self.setStyleSheet(stylesheet)

    @property
    def startup_greeting(self) -> str:
        return tr(self.greeting_key, username=self.username, name="Arlo")

    def build_worker(self):
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.initialize)
        self.request.connect(self.worker.ask)
        self.worker.ready.connect(self.on_ready)
        self.worker.chunk.connect(self.on_chunk)
        self.worker.audio.connect(self.on_audio)
        self.worker.speaking.connect(self.on_speaking)
        self.worker.finished.connect(self.on_finished)
        self.worker.failed.connect(self.on_error)

        self.thread.finished.connect(self.worker.shutdown)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.start()

        self.worker.confirmation_requested.connect(
            self.on_confirmation_requested)

    @Slot(int, str)
    def on_confirmation_requested(self, turn_id, message):
        if turn_id != self.turn_id:
            return
        if self.stopping:
            self.worker.resolve_confirmation(False)
            return
        self.set_status("status.authorization")
        dialog = QMessageBox(self)
        dialog.setWindowTitle(tr("command.title"))
        dialog.setIcon(QMessageBox.Question)
        dialog.setText(tr("command.request"))
        dialog.setInformativeText(message)
        dialog.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        dialog.button(QMessageBox.Yes).setText(tr("command.yes"))
        dialog.button(QMessageBox.No).setText(tr("command.no"))
        dialog.setDefaultButton(QMessageBox.No)

        accepted = dialog.exec() == QMessageBox.Yes
        self.worker.resolve_confirmation(accepted)
        self.set_status("status.thinking" if accepted else "status.denied")

    def set_status(self, key):
        self.status_key = key
        self.status.setText(tr(key) if key else "")

    def set_enabled(self, enabled):
        self.input.setEnabled(enabled)
        self.update_send_button()

    def update_send_button(self):
        stopping_available = self.busy and self.speaking and not self.stopping
        self.send.setText("■" if stopping_available else "")
        self.send.setEnabled(
            self.ready and (not self.busy or stopping_available))
        key = "ui.stop" if stopping_available else "ui.send"
        self.send.setAccessibleName(tr(key))
        self.send.setToolTip(tr("ui.stop_hint" if stopping_available else key))
        self.input.setPlaceholderText(
            tr("ui.steering_input" if self.busy else "ui.input"))

    @Slot(bool)
    def toggle_language(self, enabled):
        try:
            set_language("spanish" if enabled else "english")
        except (OSError, ValueError) as error:
            self.language_switch.blockSignals(True)
            self.language_switch.setChecked(get_language() == "spanish")
            self.language_switch.blockSignals(False)
            self.update_subtitles(tr("ui.error", error=error))
            return
        self.refresh_language()

    def refresh_language(self):
        language = get_language()
        if language == self.active_language:
            return
        self.active_language = language
        self.language_switch.blockSignals(True)
        self.language_switch.setChecked(language == "spanish")
        self.language_switch.blockSignals(False)
        self.subtitle_label.setText(tr("ui.subtitles"))
        self.subtitles_switch.setAccessibleName(tr("ui.subtitles"))
        self.subtitles_switch.setToolTip(tr("ui.subtitles_hint"))
        self.language_label.setText(tr("ui.language"))
        self.language_switch.setAccessibleName(tr("ui.language"))
        self.language_switch.setToolTip(tr("ui.language_hint"))
        self.set_status(self.status_key)
        self.update_send_button()
        if self.showing_greeting:
            self.update_subtitles(self.startup_greeting)

    @Slot()
    def on_ready(self):
        self.ready = True
        self.set_enabled(True)
        self.set_status("")
        self.input.setFocus()

    @Slot(bool)
    def toggle_subtitles(self, enabled: bool):
        self.subtitles.setVisible(enabled)
        self.settings.setValue("subtitles", enabled)

    def update_subtitles(self, text):
        from PySide6.QtGui import QTextLayout

        self.subtitle_text = text
        font = self.subtitles.font()
        width = max(1, self.subtitles.contentsRect().width() - 12)

        layout = QTextLayout(text, font)
        layout.beginLayout()

        lines = []
        while True:
            line = layout.createLine()
            if not line.isValid():
                break

            line.setLineWidth(width)
            start = line.textStart()
            end = start + line.textLength()
            lines.append(text[start:end])

        layout.endLayout()
        self.subtitles.setText(self.render_subtitle("\n".join(lines[-3:])))

    @staticmethod
    def render_subtitle(text: str) -> str:
        """Renderiza **negrita** sin interpretar HTML del modelo."""
        escaped = html.escape(text)
        return (re.sub(r"\*\*(.+?)\*\*",
                       r"<b>\1</b>", escaped, flags=re.DOTALL, )
                .replace("\n", "<br>"))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "subtitle_text"):
            self.update_subtitles(self.subtitle_text)

    @Slot()
    def send_message(self):
        if not self.ready:
            return

        prompt = self.input.toPlainText().strip()
        if not prompt:
            return

        if self.busy:
            if self.stopping:
                return
            self.pending_prompt = prompt
            self.input.clear()
            self.stop_response()
            return

        self.input.clear()
        self.start_prompt(prompt)

    def start_prompt(self, prompt):
        self.turn_id += 1
        self.showing_greeting = False
        self.worker.cancel_event = threading.Event()
        self.stopping = False
        self.speaking = False

        self.command_output.hide()
        self.command_output.clear()

        self.current_reply = ""
        self.update_subtitles(prompt)

        self.busy = True
        self.set_enabled(True)
        self.set_status("status.thinking")
        self.request.emit(self.turn_id, prompt)

    @Slot()
    def on_send_clicked(self):
        if self.busy:
            if self.speaking and not self.stopping:
                self.stop_response()
        else:
            self.send_message()

    def stop_response(self):
        self.stopping = True
        self.worker.interrupt()
        self.speaking = False
        self.meter.clear()
        self.set_status("status.stopping")
        self.update_send_button()

    @Slot(int, str)
    def on_chunk(self, turn_id, chunk):
        if turn_id != self.turn_id or self.current_reply is None or self.stopping:
            return

        self.current_reply += chunk
        self.update_subtitles(self.current_reply)

    @Slot(int, object)
    def on_audio(self, turn_id, levels):
        if turn_id == self.turn_id and self.busy and not self.stopping:
            self.meter.set_levels(levels)

    @Slot(int, bool)
    def on_speaking(self, turn_id, speaking):
        if turn_id != self.turn_id:
            return
        self.speaking = speaking and self.busy and not self.stopping
        if not self.stopping and self.busy:
            self.set_status(
                "status.speaking" if self.speaking else "status.thinking")
        self.update_send_button()

    @Slot(str)
    def on_finished(self, reply):
        interrupted = self.stopping
        if self.worker.command_reply:
            self.command_output.setPlainText(reply)
            self.command_output.show()
            self.update_subtitles(reply.splitlines()[0])
        elif not self.current_reply:
            self.update_subtitles(reply or tr(
                "status.stopped" if interrupted else "ui.no_response"))

        self.current_reply = None
        self.busy = False
        self.speaking = False
        self.stopping = False
        self.meter.clear()
        self.set_status("status.stopped" if interrupted else
                        "status.private" if self.worker.session.private else "")
        self.set_enabled(True)
        self.input.setFocus()
        self.resume_pending_prompt()

    def resume_pending_prompt(self):
        prompt, self.pending_prompt = self.pending_prompt, None
        if prompt:
            self.start_prompt(prompt)

    @Slot(str)
    def on_error(self, error):
        self.showing_greeting = False
        self.update_subtitles(tr("ui.error", error=error))
        self.current_reply = None
        self.busy = False
        self.speaking = False
        self.stopping = False
        self.meter.clear()
        self.set_status("status.error")
        self.set_enabled(self.ready)
        self.resume_pending_prompt()

    def closeEvent(self, event):
        if self.thread.isRunning() and self.busy:
            self.set_status(
                "status.close_wait")
            event.ignore()
            return

        if self.thread.isRunning():
            self.thread.quit()
            self.thread.wait()

        event.accept()



def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    assets = Path(__file__).resolve().parent / "assets"
    fonts = assets / "fonts"
    app.setWindowIcon(QIcon(str(assets / "pwsh.ico")))

    def load_font(filename: str) -> str:
        path = fonts / filename
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id == -1:
            raise RuntimeError(f"No se pudo cargar la fuente: {path}")

        families = QFontDatabase.applicationFontFamilies(font_id)
        if not families:
            raise RuntimeError(f"La fuente no tiene familias: {path}")

        return families[0]

    main_font_family = load_font("UbuntuNerdFont-Regular.ttf")
    secondary_font_family = load_font("JetBrainsMonoNL-Regular.ttf")
    app.setFont(QFont(main_font_family, 11))
    window = ArloWindow()
    banner_font = QFont(secondary_font_family, 11)
    banner_font.setStyleHint(QFont.Monospace)
    window.hero.setFont(banner_font)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()