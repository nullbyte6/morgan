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
import ctypes
import html
import json
import logging
import math
import os
import random
import re
import sys
import threading
from getpass import getuser
from pathlib import Path

from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtWidgets import *

from agent import Assistant
from src.init.attachment_widgets import AttachmentTray
from src.init.attachments import DesktopMessage, AttachmentSession, \
    ollama_capabilities
from src.init.brain import kill_self
from src.init.commands import execute_command, set_confirmation_handler
from src.init.config import load_dev_file, load_config
from src.init.desktop.mascot import ArloMascot
from src.init.editor.live import EditorView, ArloRing
from src.init.lang import get_language, set_language, tr
from src.init.logs import LogView
from src.init.session_log import SessionLog
from src.init.settings import SettingsView
from src.init.terminal import spectrum_levels
from src.init.voice_ipc import WakeInbox, desktop_audio

from src.init.desktop.capture import (
    CaptureRequest,
    capture_to_clipboard,
    register_capture_handler,
    unregister_capture_handler,
)

ARLO_MUTEX = r"Local\Diego.Arlo.Desktop"
_mutex_handle = None

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


def get_stylesheet():
    """Returns the global stylesheet"""
    stylesheet_path = (Path(__file__).resolve().parent / "assets" / "arlo.qss")
    stylesheet = stylesheet_path.read_text(encoding="utf-8")
    return stylesheet

class WorkingDirectory(QToolButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("directory")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAutoRaise(True)
        self.set_directory(Path.cwd())

    def set_directory(self, directory: Path | str):
        path = Path(directory).resolve()
        self.setText(f" {path.name or str(path)} ")
        self.setToolTip(str(path))


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


class VoiceInputWorker(QThread):
    levels = Signal(object)
    transcribing = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.stop_event = threading.Event()
        self.transcript = ""
        self.error = ""

    def run(self):
        try:
            from src.init.voice import record_voice, transcribe_voice

            with desktop_audio(stop_event=self.stop_event, tail=0):
                if self.isInterruptionRequested():
                    return
                recording = record_voice(
                    on_audio=self.report_audio, stop_event=self.stop_event)
                if self.isInterruptionRequested():
                    return
                if recording is None:
                    self.error = tr("voice.not_detected")
                    return
                self.transcribing.emit()
                self.transcript, _ = transcribe_voice(*recording)
                if not self.transcript:
                    self.error = tr("voice.not_transcribed")
        except Exception as error:
            self.error = str(error)

    def report_audio(self, pcm_data, sample_rate):
        import numpy as np

        samples = np.frombuffer(pcm_data, dtype="<i2").astype(np.float32) / 32768.0
        self.levels.emit(spectrum_levels(samples, sample_rate).tolist())


class AssistantWorker(QObject):
    chunk = Signal(int, str)
    audio = Signal(int, object)
    directory = Signal(str)
    speaking = Signal(int, bool)
    finished = Signal(str)
    failed = Signal(str)
    ready = Signal()
    confirmation_requested = Signal(int, str)
    accepted = Signal(int)
    rejected = Signal(int, str)
    screenshot_requested = Signal(object)
    exit_requested = Signal()

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
            self.directory.emit(str(Path.cwd()))
            self.ready.emit()
        except Exception as error:
            self.failed.emit(str(error))

    @Slot(int, object)
    def ask(self, turn_id, message):
        try:
            # Hold through agent execution, confirmation, TTS completion and
            # cancellation. Capture must stop before any synthesized speech.
            with desktop_audio(stop_event=self.cancel_event):
                self._ask(turn_id, message)
        except Exception as error:
            self.rejected.emit(turn_id, str(error))

    def _ask(self, turn_id, message):
        message = DesktopMessage(message) if isinstance(message, str) else message
        attachment_session = None
        try:
            if message.attachments:
                vision, context = ollama_capabilities(self.assistant.MODEL_NAME)
                attachment_session = AttachmentSession(
                    message, load_config()["attachments"], vision=vision,
                    context_tokens=context)
        except Exception as error:
            self.rejected.emit(turn_id, str(error))
            return
        self.accepted.emit(turn_id)
        prompt = message.text
        try:
            cancel_event = self.cancel_event
            set_confirmation_handler(
                lambda message: self.confirm_command(message, cancel_event,
                                                     turn_id))
            self.command_reply = False
            if cancel_event.is_set():
                self.finished.emit("")
                return
            privacy_result = (self.session.handle_command(prompt)
                              if not message.attachments else None)
            if privacy_result is not None:
                self.finished.emit(str(privacy_result))
                return

            self.session.write(self.assistant.username, message.log_text())
            directory_result = (self.assistant.directory_cmd(prompt)
                                if not message.attachments else None)
            if directory_result is not None:
                self.session.write(self.assistant.name, directory_result)
                self.finished.emit(directory_result)
                return

            if not message.attachments and prompt.casefold().startswith("pwsh:"):
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
                event_loop=self.event_loop,
                attachments=attachment_session)

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

        finally:
            self.directory.emit(str(Path.cwd()))
            if self.assistant.shutdown_requested.is_set():
                self.exit_requested.emit()

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


# noinspection PyBroadException
class ArloWindow(QMainWindow):
    request = Signal(int, object)
    username = getuser().capitalize()

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"ARLO {load_dev_file()["version"]}")
        icon_path = (Path(__file__).resolve().parent /
                     "assets" / "pwsh.ico")
        self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(900, 720)
        self.setMinimumSize(600, 480)

        self.mascot = ArloMascot()
        self.mascot.hide()

        self.mascot.record_requested.connect(self.on_mascot_record)
        self.mascot.restore_requested.connect(self.restore_from_mascot)
        self.mascot_shortcut = QShortcut(QKeySequence("Ctrl+Shift+M"), self)
        self.mascot_shortcut.activated.connect(self.show_mascot)

        self.arlo_ring = ArloRing(self)
        self.arlo_ring.hide()
        self.chat_button = QPushButton("󰭹")
        self.logs_button = QPushButton("")
        self.settings_button = QPushButton("")
        self.editor_button = QPushButton("󰨞")
        self.has_text = False
        self.recording = False
        self.voice_thread = None
        self.closing_after_voice = False
        self.send = QPushButton("")
        self.attach = QPushButton("")
        self.directory_indicator = WorkingDirectory(self)
        self.attachment_tray = AttachmentTray(load_config()["attachments"])
        self.submitting = None
        self.input = ChatInput()
        self.composer_widget = QWidget()
        self.input_meter = AudioVisualizer()
        self.input_meter.setMinimumWidth(0)
        self.input_meter.setFixedHeight(48)
        self.input_meter.hide()
        self.status = QLabel()
        self.command_output = QPlainTextEdit()
        self.active_language = None
        self.pages = QStackedWidget()
        self.greeting_key = f"greeting.{random.randrange(6)}"
        self.subtitles = QLabel(self.startup_greeting)
        self.hero = QLabel(Assistant().banner.strip("\n"))
        self.meter = AudioVisualizer()
        self.worker = AssistantWorker()
        self.capture_handler = self.worker.screenshot_requested.emit
        register_capture_handler(self.capture_handler)
        self.chat_scroll = QScrollArea()
        self.thread = QThread(self)

        self.log_dir = Path.home() / ".arlo" / ".log"
        self.log_view = LogView(self.log_dir, self)
        self.editor_view = EditorView(self)

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
        self.wake_inbox = None
        self.wake_command_id = None

        self.settings = QSettings("ARLO", "desktop")
        self.settings_view = SettingsView(
            self.settings.value("subtitles", True, type=bool), self)
        self.settings_view.subtitles_changed.connect(self.toggle_subtitles)
        self.settings_view.language_changed.connect(self.change_language)
        self.build_ui()

        self.next_page_shortcut = QShortcut(QKeySequence("Ctrl+Tab"), self)
        self.next_page_shortcut.setContext(Qt.WindowShortcut)
        self.next_page_shortcut.activated.connect(lambda: self.switch_page(1))

        self.previous_page_shortcut = QShortcut(QKeySequence("Ctrl+Shift+Tab"), self)
        self.previous_page_shortcut.setContext(Qt.WindowShortcut)
        self.previous_page_shortcut.activated.connect(lambda: self.switch_page(-1))

        self.build_worker()
        self.set_status("status.waking")
        self.language_timer = QTimer(self)
        self.language_timer.setInterval(500)
        self.language_timer.timeout.connect(self.refresh_language)
        self.language_timer.start()
        self.directory_timer = QTimer(self)
        self.directory_timer.setInterval(250)
        self.directory_timer.timeout.connect(
            lambda: self.directory_indicator.set_directory(Path.cwd()))
        self.directory_timer.start()
        self.wake_timer = QTimer(self)
        self.wake_timer.setInterval(250)
        self.wake_timer.timeout.connect(self.poll_wake_commands)
        self.wake_timer.start()

    def poll_wake_commands(self):
        """Consume only when ready; preserve the composer and compact mode."""
        if (not self.ready or self.busy or self.voice_thread is not None or
                self.submitting is not None or self.pending_prompt is not None or
                self.closing_after_voice or self.worker.assistant.shutdown_requested.is_set()):
            return
        try:
            if self.wake_inbox is None:
                self.wake_inbox = WakeInbox()
            command = self.wake_inbox.claim()
        except Exception:
            logging.getLogger("arlo.wake").exception("Wake inbox unavailable; will retry")
            return
        if command is None:
            return
        self.wake_command_id, text = command
        if not self.mascot.isVisible():
            self.showNormal()
            self.raise_()
            self.activateWindow()
        # Deliberately do not use the composer: draft text and attachments
        # belong to the manual interaction and must not be sent or cleared.
        self.start_prompt(DesktopMessage(text))

    def finish_wake_command(self, state, detail=""):
        command_id, self.wake_command_id = self.wake_command_id, None
        if command_id is not None:
            try:
                self.wake_inbox.finish(command_id, state, detail)
            except Exception:
                # A dispatched ID stays consumed even if acknowledgement fails.
                logging.getLogger("arlo.wake").exception("Wake acknowledgement failed")


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

        self.chat_button.setObjectName("chatNav")
        self.chat_button.setCheckable(True)
        self.chat_button.setChecked(True)
        self.chat_button.setFixedSize(48, 48)
        self.chat_button.setToolTip("Arlo")

        self.logs_button.setObjectName("logsNav")
        self.logs_button.setCheckable(True)
        self.logs_button.setFixedSize(48, 48)
        self.logs_button.setToolTip("Logs")

        self.settings_button.setObjectName("settingsNav")
        self.settings_button.setCheckable(True)
        self.settings_button.setChecked(False)
        self.settings_button.setFixedSize(48, 48)
        self.settings_button.setToolTip(tr("ui.settings"))

        self.editor_button.setObjectName("editorNav")
        self.editor_button.setCheckable(True)
        self.editor_button.setFixedSize(48, 48)
        self.editor_button.setToolTip("Editor")

        navigation.addWidget(self.chat_button)
        navigation.addWidget(self.logs_button)
        navigation.addWidget(self.settings_button)
        navigation.addWidget(self.editor_button)
        navigation.addStretch()

        container_layout.addLayout(navigation)
        self.pages.setObjectName("mainPages")

        root = QWidget()
        root.setObjectName("root")

        main = QVBoxLayout(root)
        main.setContentsMargins(20, 12, 20, 20)
        main.setSpacing(16)

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
        self.subtitles.setVisible(self.settings_view.subtitles_switch.isChecked())
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

        composer_area = QVBoxLayout()
        composer_area.setSpacing(8)

        composer = QHBoxLayout()
        composer.setSpacing(12)
        composer.setAlignment(Qt.AlignBottom)

        input_frame = QFrame()
        input_frame.setObjectName("inputFrame")
        input_frame.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Fixed
        )
        input_frame.setMinimumHeight(48)
        input_layout = QHBoxLayout(input_frame)
        input_layout.setContentsMargins(16, 0, 0, 0)
        input_layout.setSpacing(0)

        self.input.submitted.connect(self.send_message)
        input_layout.addWidget(self.input, 1, Qt.AlignVCenter)
        input_layout.addWidget(self.attach, 0, Qt.AlignBottom)
        input_layout.addWidget(self.input_meter)

        input_column = QVBoxLayout()
        input_column.setContentsMargins(0, 0, 0, 0)
        input_column.setSpacing(8)

        self.attachment_tray.setMinimumWidth(0)
        self.attachment_tray.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Fixed)

        input_column.addWidget(self.attachment_tray)
        input_column.addWidget(self.directory_indicator)
        input_column.addWidget(input_frame)

        input_group = QWidget()
        input_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        input_group.setLayout(input_column)

        self.attachment_tray.changed.connect(self.update_send_button)

        self.attach.setObjectName("attach")
        self.attach.setFixedSize(48, 48)
        self.attach.clicked.connect(self.attachment_tray.choose_files)

        self.send.setObjectName("send")
        self.send.setFixedSize(48, 48)
        self.send.clicked.connect(self.on_send_clicked)

        composer.addWidget(self.arlo_ring, 0, Qt.AlignBottom)
        composer.addWidget(input_group, 1)
        composer.addWidget(self.send, 0, Qt.AlignBottom)

        composer_container = QWidget()
        composer_container.setLayout(composer)
        composer_container.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Fixed
        )

        composer_row = QHBoxLayout()
        composer_row.setContentsMargins(20, 0, 20, 12)
        composer_row.setSpacing(0)

        composer_row.addStretch(1)
        composer_row.addWidget(composer_container, 2)
        composer_row.addStretch(1)

        composer_area.addLayout(composer_row)
        self.composer_widget.setLayout(composer_area)

        self.chat_scroll.setObjectName("chatScroll")
        self.chat_scroll.setFrameShape(QFrame.NoFrame)
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chat_scroll.setWidget(root)
        self.attachment_tray.changed.connect(self.ensure_composer_visible)
        self.input.textChanged.connect(self.ensure_composer_visible)
        self.input.textChanged.connect(self.update_send_button)
        self.pages.addWidget(self.chat_scroll)
        self.pages.addWidget(self.log_view)
        self.pages.addWidget(self.settings_view)
        self.pages.addWidget(self.editor_view)

        container_layout.addWidget(self.pages, 1)
        container_layout.addWidget(self.composer_widget)

        self.chat_button.clicked.connect(lambda: self.show_page(0))
        self.logs_button.clicked.connect(lambda: self.show_page(1))
        self.settings_button.clicked.connect(lambda: self.show_page(2))
        self.editor_button.clicked.connect(lambda: self.show_page(3))
        self.show_page(0)
        self.set_enabled(False)
        self.load_stylesheet()
        self.refresh_language()

    def ensure_composer_visible(self):
        QTimer.singleShot(0, lambda: self.chat_scroll.ensureWidgetVisible(self.input))

    def show_page(self, index: int):
        self.pages.setCurrentIndex(index)
        self.arlo_ring.setVisible(index != 0)
        self.chat_button.setChecked(index == 0)
        self.logs_button.setChecked(index == 1)
        self.settings_button.setChecked(index == 2)
        self.editor_button.setChecked(index == 3)

        if index == 1:
            self.log_view.refresh()

        if index == 0 and self.ready:
            self.input.setFocus()

    def switch_page(self, direction: int):
        count = self.pages.count()
        if count <= 1:
            return

        current = self.pages.currentIndex()
        next_index = (current + direction) % count
        self.show_page(next_index)

    def load_stylesheet(self):
        self.setStyleSheet(get_stylesheet())

    @property
    def startup_greeting(self) -> str:
        return tr(self.greeting_key, username=self.username, name="Arlo")

    def build_worker(self):
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.initialize)
        self.request.connect(self.worker.ask)
        self.worker.ready.connect(self.on_ready)
        self.worker.directory.connect(
            self.directory_indicator.set_directory
        )

        self.worker.accepted.connect(self.on_request_accepted)
        self.worker.rejected.connect(self.on_request_rejected)
        self.worker.chunk.connect(self.on_chunk)
        self.worker.audio.connect(self.on_audio)
        self.worker.speaking.connect(self.on_speaking)
        self.worker.finished.connect(self.on_finished)
        self.worker.failed.connect(self.on_error)
        self.worker.screenshot_requested.connect(self.on_screenshot_requested)
        self.worker.exit_requested.connect(self.close)

        self.thread.finished.connect(self.worker.shutdown)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.start()

        self.worker.confirmation_requested.connect(
            self.on_confirmation_requested)

    @Slot(object)
    def on_screenshot_requested(self, request: CaptureRequest):
        """Run a screenshot request on the GUI thread."""
        if request.completed.is_set():
            return

        mascot_visible = self.mascot.isVisible()
        if mascot_visible:
            self.mascot.hide()

        QTimer.singleShot(180,
            lambda: self.finish_screenshot(request, mascot_visible))

    def finish_screenshot(self, request: CaptureRequest, mascot_visible: bool):
        """Capture the screen, restore the mascot and report the result."""
        try:
            if request.completed.is_set():
                return

            request.success = capture_to_clipboard()
            if not request.success:
                request.error = "ERROR"

        except Exception as error:
            request.error = str(error)

        finally:
            if mascot_visible and not self.mascot.isVisible():
                self.mascot.show()

            request.completed.set()

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
        self.input.setEnabled(enabled and self.submitting is None)
        self.update_send_button()

    def update_send_button(self):
        self.has_text = bool(self.input.toPlainText().strip())
        voice_active = self.voice_thread is not None
        stopping_available = self.busy and self.speaking and not self.stopping
        self.send.setText("" if stopping_available or self.recording else
                          "" if self.has_text else "")
        self.send.setEnabled(
            self.ready and (self.recording or stopping_available or (
                not voice_active and not self.busy and
                self.submitting is None and self.attachment_tray.can_send)))
        editable = self.ready and self.submitting is None and not voice_active
        self.attach.setEnabled(editable)
        self.attachment_tray.setEnabled(editable)
        self.input.setEnabled(editable)
        self.attach.setToolTip(tr("ui.attach_files"))
        self.attach.setAccessibleName(tr("ui.attach_files"))
        key = ("ui.stop" if stopping_available or self.recording else
               "ui.send" if self.has_text else "voice.record")
        label = tr(key)
        self.send.setAccessibleName(label)
        self.send.setToolTip(tr("ui.stop_hint") if stopping_available else label)
        self.input.setPlaceholderText(
            tr("ui.steering_input" if self.busy else "ui.input"))

    @Slot(str)
    def change_language(self, language):
        try:
            set_language(language)
        except (OSError, ValueError) as error:
            self.settings_view.refresh_language()
            QMessageBox.warning(self, tr("ui.settings"), tr("ui.error", error=error))
            return
        self.refresh_language()

    def refresh_language(self):
        language = get_language()
        if language == self.active_language:
            return
        self.active_language = language
        self.settings_view.refresh_language()
        self.attachment_tray.refresh()
        self.settings_button.setToolTip(tr("ui.settings"))
        self.settings_button.setAccessibleName(tr("ui.settings"))
        self.set_status(self.status_key)
        self.update_send_button()
        if self.showing_greeting:
            self.update_subtitles(self.startup_greeting)

    @Slot()
    def on_ready(self):
        self.ready = True
        self.set_enabled(True)
        self.set_status("")

        if self.isVisible():
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
        """Enbold the font without rendering Markdown **"""
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
        if not self.ready or self.voice_thread is not None:
            return

        if self.submitting is not None or not self.attachment_tray.can_send:
            return
        message = DesktopMessage(self.input.toPlainText().strip(),
                                 self.attachment_tray.snapshot())
        if not message.text and not message.attachments:
            return
        if self.busy and self.stopping:
            return
        self.submitting = message
        self.update_send_button()
        if self.busy:
            self.pending_prompt = message
            self.stop_response()
            return
        self.start_prompt(message)

    @Slot(int)
    def on_request_accepted(self, turn_id):
        if turn_id != self.turn_id or self.submitting is None:
            return

        self.input.clear()
        self.attachment_tray.clear()
        self.submitting = None
        self.update_send_button()

    @Slot(int, str)
    def on_request_rejected(self, turn_id, error):
        if turn_id != self.turn_id:
            return
        self.finish_wake_command("failed", error)
        self.submitting = None
        self.busy = False
        self.current_reply = None
        self.set_status("status.error")
        self.update_send_button()
        QMessageBox.warning(self, tr("ui.attach_files"), error)

    @Slot()
    def on_mascot_record(self):
        """Start or stop microphone recording from compact mode."""
        if self.recording:
            self.on_send_clicked()
            return

        if (not self.ready or self.busy or
                self.voice_thread is not None):
            return

        self.start_recording()

    def show_mascot(self):
        """Switch to compact desktop mode."""
        self.mascot.move_to_corner()
        self.mascot.show()
        self.hide()

    def restore_from_mascot(self):
        """Restore the full Arlo interface."""
        self.mascot.hide()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def start_prompt(self, prompt):
        self.turn_id += 1
        self.showing_greeting = False
        self.worker.cancel_event = threading.Event()
        self.stopping = False
        self.speaking = False

        self.command_output.hide()
        self.command_output.clear()

        self.current_reply = ""
        self.update_subtitles(prompt.display_text)

        self.busy = True
        self.set_enabled(True)
        self.set_status("status.thinking")
        try:
            if not self.thread.isRunning():
                raise RuntimeError(tr("ui.worker_unavailable"))
            self.request.emit(self.turn_id, prompt)
        except Exception as error:
            self.on_request_rejected(self.turn_id, str(error))

    @Slot()
    def on_send_clicked(self):
        if self.recording:
            self.voice_thread.stop_event.set()
            self.recording = False
            self.update_send_button()
        elif self.voice_thread is not None:
            return
        elif self.busy:
            if self.speaking and not self.stopping:
                self.stop_response()
        elif self.has_text:
            self.send_message()
        else:
            self.start_recording()

    def start_recording(self):
        if (not self.ready or self.busy or self.submitting is not None or
                self.voice_thread is not None):
            return
        self.voice_thread = VoiceInputWorker(self)
        self.voice_thread.levels.connect(self.input_meter.set_levels)
        self.voice_thread.levels.connect(self.editor_view.set_audio_levels)
        self.voice_thread.levels.connect(self.mascot.set_levels)
        self.voice_thread.transcribing.connect(self.on_voice_transcribing)
        self.voice_thread.finished.connect(self.on_voice_finished)
        self.recording = True
        self.input.hide()
        self.input_meter.clear()
        self.input_meter.show()
        self.set_status("voice.recording")
        self.update_send_button()
        self.voice_thread.start()

    @Slot()
    def on_voice_transcribing(self):
        self.recording = False
        self.input_meter.hide()
        self.mascot.clear()
        self.input.show()
        self.set_status("voice.transcribing")
        self.update_send_button()

    @Slot()
    def on_voice_finished(self):
        worker = self.voice_thread
        self.voice_thread = None
        self.recording = False
        self.input_meter.hide()
        self.input_meter.clear()
        self.mascot.clear()
        self.input.show()
        worker.deleteLater()
        self.update_send_button()
        if self.closing_after_voice:
            self.close()
            return
        self.set_status("")
        if worker.error:
            self.status.setText(worker.error)
        elif worker.transcript:
            self.input.setPlainText(worker.transcript)
            self.send_message()

        if self.isVisible():
            self.input.setFocus()

    def stop_response(self):
        self.stopping = True
        self.worker.interrupt()
        self.speaking = False
        self.meter.clear()
        self.arlo_ring.clear()
        self.mascot.set_speaking(False)
        self.set_status("status.stopping")
        self.update_send_button()

    @Slot()
    def capture_screen(self):
        try:
            success = capture_to_clipboard()
            if success:
                self.mascot.setToolTip("Check!")
            else:
                self.mascot.setToolTip(":(")

        except Exception as error:
            self.mascot.setToolTip(f"{error}")

    @Slot(int, str)
    def on_chunk(self, turn_id, chunk):
        if turn_id != self.turn_id or self.current_reply is None or self.stopping:
            return

        self.current_reply += chunk
        self.update_subtitles(self.current_reply)
        self.arlo_ring.setToolTip(self.current_reply)

    @Slot(int, object)
    def on_audio(self, turn_id, levels):
        if turn_id == self.turn_id and self.busy and not self.stopping:
            self.meter.set_levels(levels)
            self.arlo_ring.set_levels(levels)
            self.mascot.set_levels(levels)

    @Slot(int, bool)
    def on_speaking(self, turn_id, speaking):
        if turn_id != self.turn_id:
            return
        self.speaking = speaking and self.busy and not self.stopping
        self.mascot.set_speaking(self.speaking)

        if not self.stopping and self.busy:
            self.set_status(
                "status.speaking" if self.speaking else "status.thinking")

        self.update_send_button()

    @Slot(str)
    def on_finished(self, reply):
        interrupted = self.stopping
        self.finish_wake_command("failed" if interrupted else "completed",
                                 "Interrupted" if interrupted else "")
        if self.worker.command_reply:
            self.command_output.setPlainText(reply)
            self.command_output.show()
            self.update_subtitles(reply.splitlines()[0])
        elif not self.current_reply:
            self.update_subtitles(reply or tr("status.stopped"
            if interrupted else "ui.no_response"))

        self.current_reply = None
        self.busy = False
        self.speaking = False
        self.stopping = False
        self.meter.clear()
        self.arlo_ring.clear()
        self.mascot.set_speaking(False)
        self.set_status("status.stopped" if interrupted else
                        "status.private" if self.worker.session.private else "")
        self.set_enabled(True)
        if self.isVisible():
            self.input.setFocus()

        self.resume_pending_prompt()

    def resume_pending_prompt(self):
        if self.worker.assistant.shutdown_requested.is_set():
            self.pending_prompt = None
            return
        prompt, self.pending_prompt = self.pending_prompt, None
        if prompt:
            self.start_prompt(prompt)

    @Slot(str)
    def on_error(self, error):
        self.finish_wake_command("failed", error)
        self.showing_greeting = False
        self.update_subtitles(tr("ui.error", error=error))
        self.current_reply = None
        self.busy = False
        self.speaking = False
        self.stopping = False
        self.meter.clear()
        self.arlo_ring.clear()
        self.mascot.set_speaking(False)
        self.set_status("status.error")
        self.set_enabled(self.ready)
        self.resume_pending_prompt()

    def closeEvent(self, event):
        unregister_capture_handler(self.capture_handler)
        if self.voice_thread is not None:
            self.closing_after_voice = True
            self.voice_thread.requestInterruption()
            self.voice_thread.stop_event.set()
            event.ignore()
            return
        if self.thread.isRunning() and self.busy:
            self.set_status(
                "status.close_wait")
            event.ignore()
            return

        kill_self()
        if self.thread.isRunning():
            self.thread.quit()
            self.thread.wait()

        self.mascot.close()
        event.accept()


def set_windows_app_id():
    """Identify Arlo as an independent Windows application."""
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "Diego.Arlo.Desktop")


def acquire_instance_lock() -> bool:
    """Acquire the single-instance lock for Arlo."""
    global _mutex_handle
    if sys.platform != "win32":
        return True

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_wchar_p,
    ]
    kernel32.CreateMutexW.restype = ctypes.c_void_p

    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    ERROR_ALREADY_EXISTS = 183

    handle = kernel32.CreateMutexW(
        None,
        False,
        ARLO_MUTEX,
    )

    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())

    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False

    _mutex_handle = handle
    return True


def release_instance_lock():
    """Release the lock when Arlo exits."""
    global _mutex_handle
    if _mutex_handle is not None:
        ctypes.windll.kernel32.CloseHandle(_mutex_handle)
        _mutex_handle = None


def main():
    if not acquire_instance_lock():
        return

    try:
        set_windows_app_id()
        os.chdir(Path.home())
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        assets = Path(__file__).resolve().parent / "assets"
        app.setWindowIcon(QIcon(str(assets / "pwsh.ico")))
        fonts = assets / "fonts"

        def load_font(filename: str) -> str:
            path = fonts / filename
            font_id = QFontDatabase.addApplicationFont(str(path))
            if font_id == -1:
                raise RuntimeError(f"Invalid font: {path}")

            families = QFontDatabase.applicationFontFamilies(font_id)
            if not families:
                raise RuntimeError(f"Font has no fam: {path}")

            return families[0]

        main_font = load_font("Inter_24pt-Regular.ttf")
        nerd_font = load_font("JetBrainsMonoNLNerdFontMono-Medium.ttf")
        app.setFont(QFont(main_font, 11))
        window = ArloWindow()
        window.log_view.code_font_family = nerd_font
        banner_font = QFont(nerd_font, 11)
        banner_font.setStyleHint(QFont.Monospace)
        window.hero.setFont(banner_font)
        icon_font = QFont(nerd_font, 18)

        for button in (
                window.settings_button,
                window.chat_button,
                window.logs_button,
                window.editor_button,
                window.send,
                window.attach,
                window.log_view.refresh_button,):
            button.setFont(icon_font)

        window.show()
        sys.exit(app.exec())
    finally:
        release_instance_lock()

if __name__ == "__main__":
    main()
