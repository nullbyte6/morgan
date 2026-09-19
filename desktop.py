#!/usr/bin/env python3
"""Arlo desktop interface using PySide6."""

import sys

from PySide6.QtCore import Qt, QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QPushButton, QScrollArea, QSizePolicy, QTextEdit, QVBoxLayout, QWidget
)

from agent import Assistant
from src.init.brain import get_version


class ChatInput(QTextEdit):
    submitted = Signal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not event.modifiers() & Qt.ShiftModifier:
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
        level = float(np.sqrt(np.mean(np.square(samples)))) if samples.size else 0.0
        self.audio.emit(min(1.0, level * 4))


class ArloWindow(QMainWindow):
    request = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Arlo")
        self.resize(920, 720)
        self.setMinimumSize(600, 480)

        self.busy = False
        self.ready = False
        self.current_reply = None

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
        # title = QLabel("ARLO")
        # title.setObjectName("title")
        # header.addWidget(title)
        # header.addStretch()

        version = QLabel(get_version())
        version.setObjectName("muted")
        header.addWidget(version)
        main.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.messages = QWidget()
        self.messages_layout = QVBoxLayout(self.messages)
        self.messages_layout.setContentsMargins(6, 12, 6, 12)
        self.messages_layout.setSpacing(12)

        self.hero = QLabel("ARLO")
        self.hero.setObjectName("hero")
        self.hero.setAlignment(Qt.AlignCenter)
        self.messages_layout.addWidget(self.hero)

        self.greeting = QLabel("¿En qué puedo ayudarte?")
        self.greeting.setObjectName("muted")
        self.greeting.setAlignment(Qt.AlignCenter)
        self.messages_layout.addWidget(self.greeting)
        self.messages_layout.addStretch()

        self.scroll.setWidget(self.messages)
        main.addWidget(self.scroll, 1)

        self.status = QLabel()
        self.status.setObjectName("status")
        self.status.setAlignment(Qt.AlignCenter)
        main.addWidget(self.status)

        self.meter = QLabel("▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁")
        self.meter.setObjectName("meter")
        self.meter.setAlignment(Qt.AlignCenter)
        main.addWidget(self.meter)

        input_frame = QFrame()
        input_frame.setObjectName("inputFrame")
        input_layout = QHBoxLayout(input_frame)
        input_layout.setContentsMargins(12, 8, 8, 8)

        self.input = ChatInput()
        self.input.setPlaceholderText("Escribe un mensaje...  (Shift + Enter para nueva línea)")
        self.input.setFixedHeight(76)
        self.input.submitted.connect(self.send_message)
        input_layout.addWidget(self.input, 1)

        self.send = QPushButton("Enviar")
        self.send.setObjectName("send")
        self.send.setFixedSize(82, 42)
        self.send.clicked.connect(self.send_message)
        input_layout.addWidget(self.send)

        main.addWidget(input_frame)
        self.set_enabled(False)

        self.setStyleSheet("""
            QWidget#root { background: #1e1e2e; color: #cdd6f4; }
            QLabel#title { color: #cdd6f4; font-size: 23px; font-weight: 800; letter-spacing: 3px; }
            QLabel#hero { color: #cdd6f4; font-size: 52px; font-weight: 800; margin-top: 35px; }
            QLabel#muted, QLabel#status { color: #a6adc8; font-size: 13px; }
            QLabel#meter { color: #89b4fa; font-size: 16px; }
            QScrollArea { background: transparent; border: none; }
            QScrollArea > QWidget > QWidget { background: transparent; }
            QFrame#inputFrame { background: #313244; border: 1px solid #45475a; border-radius: 16px; }
            QTextEdit { background: transparent; border: none; color: #cdd6f4; font-size: 14px; selection-background-color: #45475a; }
            QPushButton#send { background: #89b4fa; color: #1e1e2e; border: none; border-radius: 11px; font-weight: 700; }
            QPushButton#send:hover { background: #b4befe; }
            QPushButton#send:disabled { background: #45475a; color: #a6adc8; }
            QLabel#userMessage { background: #45475a; color: #cdd6f4; padding: 13px; border-radius: 12px; font-size: 14px; }
            QLabel#arloMessage { background: #313244; color: #cdd6f4; padding: 13px; border-radius: 12px; font-size: 14px; }
        """)

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

    def add_message(self, text, user=False):
        bubble = QLabel(text)
        bubble.setObjectName("userMessage" if user else "arloMessage")
        bubble.setWordWrap(True)
        bubble.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bubble.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        bubble.setMaximumWidth(650)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)

        if user:
            row.addStretch()
            row.addWidget(bubble)
        else:
            row.addWidget(bubble)
            row.addStretch()

        self.messages_layout.insertLayout(self.messages_layout.count() - 1, row)
        self.scroll_to_bottom()
        return bubble

    def scroll_to_bottom(self):
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    @Slot()
    def send_message(self):
        if self.busy or not self.ready:
            return

        prompt = self.input.toPlainText().strip()
        if not prompt:
            return

        self.hero.hide()
        self.greeting.hide()
        self.input.clear()

        self.add_message(prompt, user=True)
        self.current_reply = self.add_message("")

        self.busy = True
        self.set_enabled(False)
        self.set_status("Pensando...")
        self.request.emit(prompt)

    @Slot(str)
    def on_chunk(self, chunk):
        if self.current_reply is None:
            return

        if self.status.text() == "Pensando...":
            self.set_status("Respondiendo...")

        self.current_reply.setText(self.current_reply.text() + chunk)
        self.scroll_to_bottom()

    @Slot(float)
    def on_audio(self, level):
        heights = "▁▂▃▄▅▆▇█"
        position = min(7, max(0, int(level * 7)))
        pattern = [max(0, position - abs(7 - index) // 2) for index in range(15)]
        self.meter.setText(" ".join(heights[value] for value in pattern))

    @Slot(str)
    def on_finished(self, reply):
        if self.current_reply is not None and not self.current_reply.text():
            self.current_reply.setText(reply or "(Sin respuesta)")

        self.current_reply = None
        self.busy = False
        self.meter.setText("▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁")
        self.set_status("Listo")
        self.set_enabled(True)
        self.input.setFocus()
        self.scroll_to_bottom()

    @Slot(str)
    def on_error(self, error):
        if self.current_reply is not None:
            self.current_reply.setText(f"Error: {error}")
            self.current_reply = None
        else:
            self.add_message(f"Error: {error}")

        self.busy = False
        self.meter.setText("▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁ ▁")
        self.set_status("Error")
        self.set_enabled(self.ready)

    def closeEvent(self, event):
        if self.thread.isRunning() and self.busy:
            self.set_status("Espera a que Arlo termine de responder antes de cerrar.")
            event.ignore()
            return

        if self.thread.isRunning():
            self.thread.quit()
            self.thread.wait()

        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = ArloWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
