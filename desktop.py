#!/usr/bin/env python3
"""Arlo desktop interface using PySide6."""

import sys
import random
from getpass import getuser
from pathlib import Path

from PySide6.QtCore import Qt, QObject, QThread, Signal, Slot
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QPushButton, QSizePolicy, QTextEdit, QVBoxLayout, QWidget
)

from agent import Assistant
from src.init.brain import get_version


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


class AssistantWorker(QObject):
    chunk = Signal(str)
    audio = Signal(float)
    finished = Signal(str)
    failed = Signal(str)
    ready = Signal()

    def __init__(self):
        super().__init__()
        self.assistant = Assistant()
        self.history = []

    @Slot()
    def initialize(self):
        try:
            self.assistant._initialize_runtime()
            self.ready.emit()
        except Exception as error:
            self.failed.emit(str(error))

    @Slot(str)
    def ask(self, prompt):
        try:
            reply, self.history = self.assistant.run_desktop_turn(
                prompt,
                self.history,
                on_chunk=self.chunk.emit,
                on_audio=self.report_audio
            )
            self.finished.emit(reply)
        except Exception as error:
            self.failed.emit(str(error))

    def report_audio(self, samples, sample_rate):
        import numpy as np
        level = float(
            np.sqrt(np.mean(np.square(samples)))) if samples.size else 0.0
        self.audio.emit(min(1.0, level * 4))


class ArloWindow(QMainWindow):
    request = Signal(str)
    username = getuser().capitalize()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Arlo")
        self.resize(920, 720)
        self.setMinimumSize(600, 480)

        self.busy = False
        self.ready = False
        self.current_reply = None
        self.subtitle_text = ""

        self.build_ui()
        self.build_worker()
        self.set_status("Conectando con Arlo...")

    def build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)

        main = QVBoxLayout(root)
        main.setContentsMargins(28, 22, 28, 22)
        main.setSpacing(16)

        header = QHBoxLayout()
        version = QLabel(get_version())
        version.setObjectName("muted")
        header.addWidget(version)
        main.addLayout(header)

        banner_group = QVBoxLayout()
        banner_group.setSpacing(16)
        banner_group.setAlignment(Qt.AlignCenter)

        self.hero = QLabel(Assistant().banner.rstrip("\n"))
        self.hero.setObjectName("hero")
        self.hero.setTextFormat(Qt.PlainText)
        self.hero.setAlignment(Qt.AlignCenter)
        self.hero.setWordWrap(False)
        self.hero.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        banner_group.addWidget(self.hero)

        self.meter = QLabel("▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁")
        self.meter.setObjectName("meter")
        self.meter.setAlignment(Qt.AlignCenter)
        banner_group.addWidget(self.meter)
        main.addLayout(banner_group, 1)

        self.subtitles = QLabel(self.startup_greeting)
        self.subtitles.setObjectName("subtitles")
        self.subtitles.setAlignment(Qt.AlignCenter)
        self.subtitles.setWordWrap(True)
        self.subtitles.setTextFormat(Qt.PlainText)
        self.subtitles.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.subtitles.setFixedHeight(90)
        main.addWidget(self.subtitles)

        self.status = QLabel()
        self.status.setObjectName("status")
        self.status.setAlignment(Qt.AlignCenter)
        main.addWidget(self.status)


        composer = QHBoxLayout()
        composer.setSpacing(12)
        composer.setAlignment(Qt.AlignBottom)

        input_frame = QFrame()
        input_frame.setObjectName("inputFrame")
        input_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        input_layout = QVBoxLayout(input_frame)
        input_layout.setContentsMargins(16, 0, 16, 0)
        input_layout.setSpacing(0)

        self.input = ChatInput()
        self.input.setPlaceholderText("Escribe un mensaje...")
        self.input.submitted.connect(self.send_message)
        input_layout.addWidget(self.input, 0, Qt.AlignVCenter)

        input_frame.setMinimumHeight(48)
        composer.addWidget(input_frame, 1)

        self.send = QPushButton("")
        self.send.setObjectName("send")
        self.send.setFixedSize(48, 48)
        self.send.clicked.connect(self.send_message)
        composer.addWidget(self.send, 0, Qt.AlignVCenter)
        main.addLayout(composer)

        self.set_enabled(False)
        self.load_stylesheet()

    def load_stylesheet(self):
        stylesheet_path = (
                    Path(__file__).resolve().parent / "assets" / "arlo.qss")
        stylesheet = stylesheet_path.read_text(encoding="utf-8")
        self.setStyleSheet(stylesheet)

    @property
    def startup_greeting(self) -> str:
        greetings = (
            f"Hola, {self.username}. ¿Qué quieres hacer?",
            f"Hola, {self.username}. ¿En qué te ayudo?",
            f"Estoy listo, {self.username}. ¿Qué hacemos?",
            f"¿Qué necesitas hoy, {self.username}?",
            f"Todo listo, {self.username}. ¿Por dónde empezamos?",
            f"Arlo preparado. Escribe lo que necesites.",
        )
        return random.choice(greetings)

    def build_worker(self):
        self.thread = QThread(self)
        self.worker = AssistantWorker()
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.initialize)
        self.request.connect(self.worker.ask)
        self.worker.ready.connect(self.on_ready)
        self.worker.chunk.connect(self.on_chunk)
        self.worker.audio.connect(self.on_audio)
        self.worker.finished.connect(self.on_finished)
        self.worker.failed.connect(self.on_error)

        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.start()

    def set_status(self, text):
        self.status.setText(text)

    def set_enabled(self, enabled):
        self.input.setEnabled(enabled)
        self.send.setEnabled(enabled)

    @Slot()
    def on_ready(self):
        self.ready = True
        self.set_enabled(True)
        self.set_status("")
        self.input.setFocus()

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

        self.subtitles.setText("\n".join(lines[-3:]))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "subtitle_text"):
            self.update_subtitles(self.subtitle_text)

    @Slot()
    def send_message(self):
        if self.busy or not self.ready:
            return

        prompt = self.input.toPlainText().strip()
        if not prompt:
            return

        self.input.clear()
        self.current_reply = ""
        self.update_subtitles(prompt)

        self.busy = True
        self.set_enabled(False)
        self.set_status("Pensando...")
        self.request.emit(prompt)

    @Slot(str)
    def on_chunk(self, chunk):
        if self.current_reply is None:
            return

        self.current_reply += chunk
        self.update_subtitles(self.current_reply)

    @Slot(float)
    def on_audio(self, level):
        heights = "▁▂▃▄▅▆▇█"
        position = min(7, max(0, int(level * 7)))
        pattern = [max(0, position - abs(7 - index) // 2) for index in
                   range(15)]
        self.meter.setText(" ".join(heights[value] for value in pattern))

    @Slot(str)
    def on_finished(self, reply):
        if not self.current_reply:
            self.update_subtitles(reply or "(Sin respuesta)")

        self.current_reply = None
        self.busy = False
        self.meter.setText("▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁")
        self.set_status("")
        self.set_enabled(True)
        self.input.setFocus()

    @Slot(str)
    def on_error(self, error):
        self.update_subtitles(f"Error: {error}")
        self.current_reply = None
        self.busy = False
        self.meter.setText("▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁")
        self.set_status("Error")
        self.set_enabled(self.ready)

    def closeEvent(self, event):
        if self.thread.isRunning() and self.busy:
            self.set_status(
                "Espera a que Arlo termine de responder antes de cerrar.")
            event.ignore()
            return

        if self.thread.isRunning():
            self.thread.quit()
            self.thread.wait()

        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    font_path = (Path(
        __file__).resolve().parent / "assets" / "fonts" /
                 "JetBrainsMonoNL-Regular.ttf")
    font_id = QFontDatabase.addApplicationFont(str(font_path))
    if font_id == -1:
        pass
    else:
        family = QFontDatabase.applicationFontFamilies(font_id)[0]
        app.setFont(QFont(family, 11))

    window = ArloWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
