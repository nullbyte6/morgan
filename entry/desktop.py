#!/usr/bin/env python3
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
import logging
import math
import os
import random
import re
import sys
import threading
from getpass import getuser
from pathlib import Path

from src.tools.resources import resource_path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import *

from entry.agent import Assistant
from src.init.attachment_widgets import AttachmentTray
from src.init.attachments import DesktopMessage, AttachmentSession, \
    ollama_capabilities
from src.init.brain import kill_self
from src.init.commands import execute_command, set_confirmation_handler
from src.init.config import load_dev_file, load_config
from src.init.editor.live import EditorView
from src.init.lang import get_language, set_language, tr
from src.init.logs import LogView
from src.init.session_log import SessionLog
from src.init.settings import SettingsView
from src.init.terminal import spectrum_levels
from src.init.voice_ipc import (
    WAKE_RECORD_REQUEST,
    ProcessLock,
    WakeInbox,
    desktop_audio,
)

from src.init.desktop.capture import (
    CaptureRequest,
    capture_to_clipboard,
    register_capture_handler,
    unregister_capture_handler,
)
from src.init.desktop.clipboard import (
    ClipboardRequest,
    read_clipboard_on_gui_thread,
    register_clipboard_handler,
    unregister_clipboard_handler,
)

ARLO_INSTANCE_SERVER = "Diego.Arlo.Desktop"


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
    stylesheet_path = resource_path(
        (Path(__file__).resolve().parent.parent / "assets" / "arlo.qss"))
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


class PrivacyIndicator(QToolButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("privacyIndicator")
        self.setText(tr("status.private"))
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setAutoRaise(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed
        )

        self.hide()


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

    def __init__(self, parent=None, *, automatic=False):
        super().__init__(parent)
        self.automatic = automatic
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
                    on_audio=self.report_audio, stop_event=self.stop_event,
                    stop_on_silence=self.automatic)
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

        samples = np.frombuffer(pcm_data, dtype="<i2").astype(
            np.float32) / 32768.0
        self.levels.emit(spectrum_levels(samples, sample_rate).tolist())


# noinspection PyBroadException
class AssistantWorker(QObject):
    chunk = Signal(int, str)
    audio = Signal(int, object)
    directory = Signal(str)
    speaking = Signal(int, bool)
    subtitle = Signal(int, str)
    finished = Signal(str)
    failed = Signal(str)
    ready = Signal()
    confirmation_requested = Signal(int, str)
    accepted = Signal(int)
    rejected = Signal(int, str)
    screenshot_requested = Signal(object)
    clipboard_requested = Signal(object)
    exit_requested = Signal()

    def __init__(self, startup_greeting=""):
        super().__init__()
        self.assistant = Assistant()
        self.startup_greeting = startup_greeting
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
            if self.startup_greeting:
                voice = self.assistant.voice
                voice.audio_callback = lambda samples, rate: self.report_audio(
                    0, samples, rate)
                voice.speaking_callback = lambda speaking: self.speaking.emit(
                    0, speaking)
                voice.subtitle_callback = lambda text: self.subtitle.emit(0,
                                                                          text)
                try:
                    with desktop_audio():
                        voice.begin_turn()
                        voice.enqueue(self.startup_greeting)
                        voice.wait_until_done()
                except Exception:
                    logging.getLogger("arlo.voice").exception(
                        "Unable to play startup greeting")
                finally:
                    voice.audio_callback = None
                    voice.speaking_callback = None
                    voice.subtitle_callback = None
                    self.speaking.emit(0, False)
            self.directory.emit(str(Path.cwd()))
            self.ready.emit()
        except Exception as error:
            self.failed.emit(str(error))

    @Slot(int, object)
    def ask(self, turn_id, message):
        try:
            with desktop_audio(stop_event=self.cancel_event):
                self._ask(turn_id, message)
        except Exception as error:
            self.rejected.emit(turn_id, str(error))

    def _ask(self, turn_id, message):
        message = DesktopMessage(message) if isinstance(message,
                                                        str) else message
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
            from src.init.hot_reload import is_reload_command
            if not message.attachments and is_reload_command(prompt):
                reply = self.assistant.reload_source()
                self.session.write(self.assistant.name, reply)
                self.finished.emit(reply)
                return
            directory_result = (self.assistant.directory_cmd(prompt)
                                if not message.attachments else None)
            if directory_result is not None:
                self.session.write(self.assistant.name, directory_result)
                self.finished.emit(directory_result)
                return

            if not message.attachments and prompt.casefold().startswith(
                    "pwsh:"):
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
                on_subtitle=lambda text: self.subtitle.emit(turn_id, text),
                cancel_event=cancel_event,
                event_loop=self.event_loop,
                attachments=attachment_session, session=self.session)

            if reply:
                self.session.write(self.assistant.name, reply,
                                   status="interrupted" if cancel_event.is_set() else "completed")

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
        self.session.close()
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


def compact_mascot_subtitle(text: str, limit: int = 64) -> str:
    """Return a single compact subtitle fragment capped at 'limit' chars."""
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[:limit - 1].rstrip() + "…"


class MascotSubtitleBubble(QWidget):
    """Animated, right-anchored subtitle ticker for the floating mascot."""
    WIDTH = 320
    GAP = 3
    PADDING_X = 12
    PADDING_Y = 10
    ANIMATION_MS = 120

    def __init__(self, mascot):
        super().__init__(None)
        self.mascot = mascot
        self._active = False

        self._source_text = ""
        self._visible_text = ""
        self._previous_text = ""
        self._offset = 0.0

        self.setObjectName("mascotSubtitleBubble")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self.setFixedWidth(self.WIDTH)
        self.setFixedHeight(
            self.fontMetrics().height() + self.PADDING_Y * 2 + 4
        )

        self.animation = QPropertyAnimation(self, b"offset", self)
        self.animation.setDuration(self.ANIMATION_MS)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.mascot.installEventFilter(self)
        self.hide()

    @Property(float)
    def offset(self):
        return self._offset

    @offset.setter
    def offset(self, value):
        self._offset = float(value)
        self.update()

    def _fit_text(self, text):
        """Keep the newest words within the available width."""
        metrics = self.fontMetrics()
        available = self.width() - self.PADDING_X * 2

        words = text.split()

        while len(words) > 1:
            candidate = " ".join(words)

            if metrics.horizontalAdvance(candidate) <= available:
                return candidate

            words.pop(0)

        if not words:
            return ""

        word = words[0]

        if metrics.horizontalAdvance(word) <= available:
            return word

        return metrics.elidedText(word, Qt.TextElideMode.ElideLeft,
            available)

    def set_subtitle(self, text: str, active: bool):
        """Receive the latest subtitle without changing the TTS pipeline."""
        subtitle = " ".join(str(text or "").split())
        self._active = bool(active and subtitle)

        if not self._active:
            self.animation.stop()
            self._source_text = ""
            self._visible_text = ""
            self._previous_text = ""
            self._offset = 0.0
            self.hide()
            return

        if subtitle != self._source_text:
            old_source = self._source_text
            old_visible = self._visible_text

            self._source_text = subtitle
            self._visible_text = self._fit_text(subtitle)

            appended = (
                bool(old_source)
                and subtitle.startswith(old_source)
                and len(subtitle) > len(old_source))
            self.animation.stop()

            if appended:
                metrics = self.fontMetrics()
                addition = subtitle[len(old_source):]
                distance = metrics.horizontalAdvance(addition)

                self._previous_text = old_visible
                self._offset = float(distance)
                self.animation.setStartValue(float(distance))
                self.animation.setEndValue(0.0)
                self.animation.start()

            else:
                self._previous_text = ""
                self._offset = 0.0

        if not self.mascot.isVisible():
            self.hide()
            return

        self.reposition()
        self.show()
        self.raise_()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        option = QStyleOption()
        option.initFrom(self)

        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget,
            option, painter, self)

        if not self._visible_text:
            painter.end()
            return

        metrics = self.fontMetrics()

        left = self.PADDING_X
        right = self.width() - self.PADDING_X
        top = self.PADDING_Y

        available = right - left
        painter.save()
        painter.setClipRect(QRectF(left, top, available,
                self.height() - self.PADDING_Y * 2))

        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        painter.setFont(self.font())

        baseline = ((self.height() - metrics.height()) / 2 + metrics.ascent())
        text_width = metrics.horizontalAdvance(self._visible_text)
        x = right - text_width + self._offset
        painter.drawText(QPointF(x, baseline),self._visible_text)

        painter.restore()
        painter.end()

    def reposition(self):
        screen = (QApplication.screenAt(self.mascot.frameGeometry().center())
            or QApplication.primaryScreen())
        if screen is None:
            return

        area = screen.availableGeometry()
        mascot = self.mascot.frameGeometry()
        bubble = self.frameGeometry()

        left_x = mascot.left() - bubble.width() - self.GAP
        right_x = mascot.right() + self.GAP + 1

        if left_x >= area.left():
            x = left_x
        else:
            x = min(right_x, area.right() - bubble.width() + 1)

        y = mascot.center().y() - bubble.height() // 2
        y = max(area.top(),min(y, area.bottom() - bubble.height() + 1))

        self.move(x, y)

    def eventFilter(self, watched, event):
        if watched is self.mascot:

            if event.type() in (QEvent.Type.Move, QEvent.Type.Resize):
                if self.isVisible():
                    self.reposition()

            elif event.type() == QEvent.Type.Show and self._active:
                QTimer.singleShot(0, self._show_for_mascot)

            elif event.type() == QEvent.Type.Hide:
                self.hide()

        return super().eventFilter(watched, event)

    def _show_for_mascot(self):
        if self._active and self.mascot.isVisible():
            self.reposition()
            self.show()
            self.raise_()

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
        self.speech_scale += (
                                     speech_scale_target - self.speech_scale) * scale_factor

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


# noinspection PyBroadException
class ArloWindow(QMainWindow):
    request = Signal(int, object)
    username = getuser().capitalize()

    def __init__(self):
        super().__init__()
        self.settings = QSettings("ARLO", "desktop")
        subtitles_enabled = self.settings.value(
            "subtitles", True, type=bool)
        orb_speech_pulse = self.settings.value(
            "orb_speech_pulse", True, type=bool)
        self.setWindowTitle(f"ARLO {load_dev_file()["version"]}")
        icon_path = (Path(__file__).resolve().parent.parent /
                     "assets" / "arlo.ico")
        self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(900, 720)
        self.setMinimumSize(600, 480)

        self.mascot = Orb(
            size=120, floating=True, line_width=2.8, fill_ratio=0.6)
        self.mascot.set_speech_pulse_enabled(orb_speech_pulse)
        self.mascot.hide()
        self.mascot_subtitles = MascotSubtitleBubble(self.mascot)
        self.subtitles_enabled = subtitles_enabled

        self.mascot.record_requested.connect(self.on_mascot_record)
        self.mascot.restore_requested.connect(self.restore_from_mascot)
        self.mascot_shortcut = QShortcut(QKeySequence("Ctrl+Shift+M"), self)
        self.mascot_shortcut.activated.connect(self.show_mascot)

        self.composer_orb = Orb(
            self, size=84, line_width=2.6, fill_ratio=0.6)
        self.composer_orb.set_speech_pulse_enabled(orb_speech_pulse)
        self.composer_orb.hide()
        self.chat_button = QPushButton("󰭹")
        self.logs_button = QPushButton("")
        self.settings_button = QPushButton("")
        self.editor_button = QPushButton("󰨞")
        self.has_text = False
        self.recording = False
        self.voice_thread = None
        self.closing_after_voice = False
        self.quitting = False
        self.send = QPushButton("")
        self.attach = QPushButton("")
        self.directory_indicator = WorkingDirectory(self)
        self.privacy_indicator = PrivacyIndicator(self)
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

        self.orb = Orb(self, fill_ratio=0.6)
        self.orb.set_speech_pulse_enabled(orb_speech_pulse)

        self.worker = AssistantWorker(self.startup_greeting)
        self.capture_handler = self.worker.screenshot_requested.emit
        register_capture_handler(self.capture_handler)
        self.clipboard_handler = self.worker.clipboard_requested.emit
        register_clipboard_handler(self.clipboard_handler)
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

        self.settings_view = SettingsView(
            subtitles_enabled,
            orb_speech_pulse,
            self)
        self.settings_view.subtitles_changed.connect(self.toggle_subtitles)
        self.settings_view.orb_pulse_changed.connect(
            self.toggle_orb_speech_pulse)
        self.settings_view.language_changed.connect(self.change_language)
        self.build_ui()

        self.next_page_shortcut = QShortcut(QKeySequence("Ctrl+Tab"), self)
        self.next_page_shortcut.setContext(Qt.WindowShortcut)
        self.next_page_shortcut.activated.connect(lambda: self.switch_page(1))

        self.previous_page_shortcut = QShortcut(QKeySequence("Ctrl+Shift+Tab"),
                                                self)
        self.previous_page_shortcut.setContext(Qt.WindowShortcut)
        self.previous_page_shortcut.activated.connect(
            lambda: self.switch_page(-1))

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
            logging.getLogger("arlo.wake").exception(
                "Wake inbox unavailable; will retry")
            return
        if command is None:
            return
        command_id, text = command
        if text == WAKE_RECORD_REQUEST:
            self.wake_command_id = command_id
            self.start_recording(automatic=True)
            self.finish_wake_command(
                "completed" if self.recording else "failed",
                "" if self.recording else "Recording was unavailable",
            )
            return
        self.wake_command_id = command_id
        self.start_prompt(DesktopMessage(text))

    def finish_wake_command(self, state, detail=""):
        command_id, self.wake_command_id = self.wake_command_id, None
        if command_id is not None:
            try:
                self.wake_inbox.finish(command_id, state, detail)
            except Exception:
                logging.getLogger("arlo.wake").exception(
                    "Wake acknowledgement failed")

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
        banner_group.addWidget(self.orb, 0, Qt.AlignCenter)
        main.addLayout(banner_group, 1)

        self.status.setObjectName("status")
        self.status.setAlignment(Qt.AlignCenter)
        main.addWidget(self.status)

        self.subtitles.setObjectName("subtitles")
        self.subtitles.setAlignment(Qt.AlignCenter)
        self.subtitles.setWordWrap(True)
        self.subtitles.setTextFormat(Qt.RichText)
        self.subtitles.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.subtitles.setFixedHeight(90)
        self.subtitles.setVisible(
            self.settings_view.subtitles_switch.isChecked())
        main.addWidget(self.subtitles)

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
        input_layout.addWidget(self.input_meter)
        input_layout.addWidget(self.attach, 0, Qt.AlignBottom)

        input_column = QVBoxLayout()
        input_column.setContentsMargins(0, 0, 0, 0)
        input_column.setSpacing(8)

        self.attachment_tray.setMinimumWidth(0)
        self.attachment_tray.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Fixed)

        input_column.addWidget(self.attachment_tray)
        indicator_row = QHBoxLayout()
        indicator_row.setContentsMargins(0, 0, 0, 0)
        indicator_row.setSpacing(6)
        indicator_row.addWidget(self.directory_indicator)
        indicator_row.addWidget(self.privacy_indicator)
        indicator_row.addStretch()
        input_column.addLayout(indicator_row)
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

        composer.addWidget(self.composer_orb, 0, Qt.AlignBottom)
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
        QTimer.singleShot(0, lambda: self.chat_scroll.ensureWidgetVisible(
            self.input))

    def show_page(self, index: int):
        self.pages.setCurrentIndex(index)
        self.composer_orb.setVisible(index != 0)
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
        self.worker.subtitle.connect(self.on_subtitle)
        self.worker.finished.connect(self.on_finished)
        self.worker.failed.connect(self.on_error)
        self.worker.screenshot_requested.connect(self.on_screenshot_requested)
        self.worker.clipboard_requested.connect(self.on_clipboard_requested)
        self.worker.exit_requested.connect(self.request_quit)

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
                          lambda: self.finish_screenshot(request,
                                                         mascot_visible))

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

    @Slot(object)
    def on_clipboard_requested(self, request: ClipboardRequest):
        """Read Qt's clipboard on the GUI thread for an assistant tool call."""
        if request.completed.is_set():
            return
        try:
            request.value = read_clipboard_on_gui_thread()
            request.success = request.value is not None
            if not request.success:
                request.error = "The clipboard is empty or unsupported."
        except Exception as error:
            request.error = str(error)
        finally:
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
        self.send.setToolTip(
            tr("ui.stop_hint") if stopping_available else label)
        self.input.setPlaceholderText(
            tr("ui.steering_input" if self.busy else "ui.input"))

    @Slot(str)
    def change_language(self, language):
        try:
            set_language(language)
        except (OSError, ValueError) as error:
            self.settings_view.refresh_language()
            QMessageBox.warning(self, tr("ui.settings"),
                                tr("ui.error", error=error))
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

    def refresh_privacy_indicator(self):
        private = self.worker.session.private
        self.privacy_indicator.setVisible(private)

    @Slot()
    def on_ready(self):
        self.ready = True
        self.set_enabled(True)
        self.set_status("")

        if self.isVisible():
            self.input.setFocus()

    @Slot(bool)
    def toggle_subtitles(self, enabled: bool):
        self.subtitles_enabled = enabled
        self.subtitles.setVisible(enabled)
        self.sync_mascot_subtitle()
        self.settings.setValue("subtitles", enabled)

    def toggle_orb_speech_pulse(self, enabled: bool):
        for orb in (self.orb, self.composer_orb, self.mascot):
            orb.set_speech_pulse_enabled(enabled)
        self.settings.setValue("orb_speech_pulse", enabled)

    def set_orbs_speaking(self, speaking: bool):
        for orb in (self.orb, self.composer_orb, self.mascot):
            orb.set_speaking(speaking)
        self.sync_mascot_subtitle()

    def sync_mascot_subtitle(self):
        self.mascot_subtitles.set_subtitle(
            self.subtitle_text,
            self.subtitles_enabled and self.speaking)

    def update_subtitles(self, text):
        from PySide6.QtGui import QTextLayout
        self.subtitle_text = text
        font = self.subtitles.font()
        metrics = QFontMetrics(font)
        max_width = metrics.horizontalAdvance("M" * 56)
        available = max(1, self.subtitles.contentsRect().width() - 24)

        width = min(max_width, available)
        lines = []

        for paragraph in text.split("\n"):
            if not paragraph:
                lines.append("")
                continue

            layout = QTextLayout(paragraph, font)
            layout.beginLayout()
            while True:
                line = layout.createLine()
                if not line.isValid():
                    break

                line.setLineWidth(width)
                start = line.textStart()
                end = start + line.textLength()
                lines.append(paragraph[start:end])
            layout.endLayout()

        self.subtitles.setText(self.render_subtitle("\n".join(lines[-3:])))
        self.sync_mascot_subtitle()

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
        if self.quitting:
            return
        self.mascot.hide()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    @Slot()
    def request_quit(self):
        """Explicitly stop Arlo; ordinary window closes only hide it."""
        if self.quitting:
            return
        self.quitting = True
        kill_self()
        self.close()

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

    def start_recording(self, *, automatic=False):
        if (not self.ready or self.busy or self.submitting is not None or
                self.voice_thread is not None):
            return
        self.voice_thread = VoiceInputWorker(self, automatic=automatic)
        self.voice_thread.levels.connect(self.input_meter.set_levels)
        self.voice_thread.levels.connect(self.mascot.set_levels)
        self.voice_thread.transcribing.connect(self.on_voice_transcribing)
        self.voice_thread.finished.connect(self.on_voice_finished)
        self.recording = True
        self.mascot.set_listening(True)
        self.input.hide()
        self.input_meter.clear()
        self.input_meter.show()
        self.set_status("voice.recording")
        self.update_send_button()
        self.voice_thread.start()

    @Slot()
    def on_voice_transcribing(self):
        self.recording = False
        self.mascot.set_listening(False)
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
        self.mascot.set_listening(False)
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
        self.orb.clear()
        self.composer_orb.clear()
        self.set_orbs_speaking(False)
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
        self.composer_orb.setToolTip(self.current_reply)

    @Slot(int, str)
    def on_subtitle(self, turn_id, text):
        if turn_id == self.turn_id and not self.stopping:
            self.update_subtitles(text)

    @Slot(int, object)
    def on_audio(self, turn_id, levels):
        if (turn_id == self.turn_id and (self.busy or not self.ready)
                and not self.stopping):
            self.composer_orb.set_levels(levels)
            self.mascot.set_levels(levels)
            self.orb.set_levels(levels)

    @Slot(int, bool)
    def on_speaking(self, turn_id, speaking):
        if turn_id != self.turn_id:
            return
        self.speaking = (speaking and (self.busy or not self.ready)
                         and not self.stopping)
        self.set_orbs_speaking(self.speaking)

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
        else:
            self.update_subtitles("")

        self.current_reply = None
        self.busy = False
        self.speaking = False
        self.stopping = False
        self.orb.clear()
        self.composer_orb.clear()
        self.set_orbs_speaking(False)
        self.set_status("status.stopped" if interrupted else "")
        self.refresh_privacy_indicator()
        self.set_enabled(True)
        if self.isVisible():
            self.input.setFocus()

        self.resume_pending_prompt()
        if self.quitting:
            QTimer.singleShot(0, self.close)

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
        self.orb.clear()
        self.composer_orb.clear()
        self.set_orbs_speaking(False)
        self.set_status("status.error")
        self.set_enabled(self.ready)
        self.resume_pending_prompt()
        if self.quitting:
            QTimer.singleShot(0, self.close)

    def closeEvent(self, event):
        if not self.quitting:
            self.mascot.hide()
            self.hide()
            event.ignore()
            return

        unregister_capture_handler(self.capture_handler)
        unregister_clipboard_handler(self.clipboard_handler)
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
        QTimer.singleShot(0, QApplication.instance().quit)


def set_windows_app_id():
    """Identify Arlo as an independent Windows application."""
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "Diego.Arlo.Desktop")


def notify_running_instance(timeout_ms: int = 1500) -> bool:
    """Ask an existing desktop process to bring its window to the front."""
    socket = QLocalSocket()
    socket.connectToServer(
        ARLO_INSTANCE_SERVER,
        QIODevice.OpenModeFlag.WriteOnly,
    )
    if not socket.waitForConnected(timeout_ms):
        return False
    socket.write(b"activate\n")
    socket.flush()
    socket.waitForBytesWritten(timeout_ms)
    socket.disconnectFromServer()
    return True


def acquire_instance_lock() -> QLockFile | None:
    """Keep initialization races from creating two desktop processes."""
    lock_path = (Path(QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.TempLocation)) /
                 f"arlo-desktop-{getuser()}.lock")
    lock = QLockFile(str(lock_path))
    return lock if lock.tryLock(100) else None


def start_instance_server() -> QLocalServer:
    """Open the local activation endpoint for the lock-owning process."""
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    if server.listen(ARLO_INSTANCE_SERVER):
        return server

    QLocalServer.removeServer(ARLO_INSTANCE_SERVER)
    if not server.listen(ARLO_INSTANCE_SERVER):
        raise RuntimeError(server.errorString())
    return server


def install_tray_icon(app: QApplication, window: ArloWindow, icon: QIcon):
    """Install the system tray UI where the desktop environment supports it."""
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return None

    tray = QSystemTrayIcon(icon, app)
    tray.setToolTip(tr("tray.running"))
    menu = QMenu(window)
    open_action = menu.addAction(tr("tray.open"))
    quit_action = menu.addAction(tr("tray.quit"))
    open_action.triggered.connect(window.restore_from_mascot)
    quit_action.triggered.connect(window.request_quit)
    tray.setContextMenu(menu)

    def activate(reason):
        if reason in (
                QSystemTrayIcon.ActivationReason.Trigger,
                QSystemTrayIcon.ActivationReason.DoubleClick):
            window.restore_from_mascot()

    tray.activated.connect(activate)
    tray.show()
    return tray


def main():
    set_windows_app_id()
    os.chdir(Path.home())
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    instance_lock = acquire_instance_lock()
    if instance_lock is None:
        for _ in range(12):
            if notify_running_instance(250):
                break
            QThread.msleep(100)
        return

    running_lock = ProcessLock("desktop-running")
    if not running_lock.acquire():
        instance_lock.unlock()
        return

    instance_server = start_instance_server()

    try:
        app.setStyle("Fusion")
        assets = Path(__file__).resolve().parent.parent / "assets"
        app_icon = QIcon(str(assets / "arlo.ico"))
        app.setWindowIcon(app_icon)
        fonts = assets / "fonts"

        def load_font(filename: str) -> str:
            path = resource_path(fonts, filename)
            if not path.is_file():
                raise FileNotFoundError(
                    f"Font file not found: {path}"
                )

            font_id = QFontDatabase.addApplicationFont(str(path))
            if font_id == -1:
                raise RuntimeError(
                    f"Qt could not load font: {path}")

            families = QFontDatabase.applicationFontFamilies(font_id)
            if not families:
                raise RuntimeError(
                    f"No font families found in: {path}")

            return families[0]

        main_font = load_font("Inter_24pt-Regular.ttf")
        nerd_font = load_font("JetBrainsMonoNLNerdFontMono-Medium.ttf")
        app.setFont(QFont(main_font, 11))
        window = ArloWindow()
        window.log_view.code_font_family = nerd_font
        banner_font = QFont(nerd_font, 11)
        banner_font.setStyleHint(QFont.Monospace)
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

        def activate_existing_window():
            while instance_server.hasPendingConnections():
                connection = instance_server.nextPendingConnection()
                connection.readAll()
                connection.disconnectFromServer()
                connection.deleteLater()
            window.restore_from_mascot()

        instance_server.newConnection.connect(activate_existing_window)
        if instance_server.hasPendingConnections():
            QTimer.singleShot(0, activate_existing_window)

        tray_icon = install_tray_icon(app, window, app_icon)
        window.tray_icon = tray_icon
        window.show()
        sys.exit(app.exec())
    finally:
        instance_server.close()
        QLocalServer.removeServer(ARLO_INSTANCE_SERVER)
        instance_lock.unlock()
        running_lock.release()


if __name__ == "__main__":
    main()
