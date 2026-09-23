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
"""Embedded terminal with an independent, persistent shell per workspace."""
from __future__ import annotations

import os
import queue
import select
import shutil
import signal
import subprocess
import sys
from pathlib import Path

import pyte
from PySide6.QtCore import Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont, QKeySequence, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import *


class TerminalSession(QThread):
    """Own the PTY off the GUI thread; all writes and resizes are queued."""

    output = Signal(str)
    failed = Signal(str)
    exited = Signal(int)

    def __init__(self, directory: Path, columns=80, rows=24):
        super().__init__(QApplication.instance())
        self.directory = directory
        self.columns, self.rows = columns, rows
        self.commands = queue.Queue()
        self.pid = None
        QApplication.instance().aboutToQuit.connect(self.shutdown)

    def write(self, text):
        self.commands.put(("write", text))

    def resize_terminal(self, columns, rows):
        self.commands.put(("resize", (columns, rows)))

    @Slot()
    def stop(self):
        self.requestInterruption()

    @Slot()
    def shutdown(self):
        self.stop()
        self.wait(10000)

    def run(self):
        process = None
        exit_code = -1
        try:
            environment = dict(os.environ, TERM="xterm-256color")
            if os.name == "nt":
                from winpty import PTY
                process = PTY(self.columns, self.rows, timeout=3000)
                shell = shutil.which("pwsh.exe") or str(
                    Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
                    / "PowerShell" / "7" / "pwsh.exe")
                if not Path(shell).is_file():
                    raise FileNotFoundError(f"PowerShell 7 (pwsh.exe) not found: {shell}")
                python = Path(sys.executable)
                if python.name.lower() == "pythonw.exe":
                    python = python.with_name("python.exe")
                bootstrap = Path(__file__).with_name("desktop") / "terminal_shell.py"
                process.spawn(str(python),
                              cmdline=" " + subprocess.list2cmdline([str(bootstrap), shell]),
                              cwd=str(self.directory),
                              env="\0".join(f"{k}={v}" for k, v in environment.items()) + "\0")
            else:
                from ptyprocess import PtyProcessUnicode
                shell = os.environ.get("SHELL") or shutil.which("sh") or "/bin/sh"
                process = PtyProcessUnicode.spawn(
                    [shell, "-i"], cwd=str(self.directory), env=environment,
                    dimensions=(self.rows, self.columns))
            self.pid = process.pid
            while not self.isInterruptionRequested():
                for _ in range(64):
                    try:
                        action, value = self.commands.get_nowait()
                    except queue.Empty:
                        break
                    if action == "write":
                        process.write(value)
                    elif os.name == "nt":
                        process.set_size(*value)
                    else:
                        process.setwinsize(value[1], value[0])
                if os.name == "nt":
                    data = process.read(blocking=False)
                elif select.select([process.fd], [], [], 0)[0]:
                    data = process.read(65536)
                else:
                    data = ""
                if data:
                    self.output.emit(data)
                if not process.isalive():
                    exit_code = (process.get_exitstatus() if os.name == "nt"
                                 else process.exitstatus) or 0
                    break
                self.msleep(10)
        except EOFError:
            exit_code = 0
        except Exception as error:
            if not self.isInterruptionRequested():
                self.failed.emit(str(error))
        finally:
            if process is not None and self.pid is not None:
                try:
                    if process.isalive():
                        if os.name == "nt":
                            subprocess.run(
                                ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)
                        else:
                            os.killpg(process.pid, signal.SIGKILL)
                    if os.name != "nt":
                        process.close(force=True)
                except Exception as error:
                    self.failed.emit(f"Could not close terminal: {error}")
            self.exited.emit(exit_code)


class TerminalScreen(pyte.HistoryScreen):
    """Reply to terminal device/cursor queries through the same PTY."""

    def __init__(self, send):
        self.send = send
        super().__init__(80, 24, history=1000)

    def write_process_input(self, data):
        self.send(data)


class TerminalDisplay(QPlainTextEdit):
    input_received = Signal(str)
    resized = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("terminalOutput")
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        font = QFont("JetBrainsMono Nerd Font Mono", 11)
        font.setStyleHint(QFont.Monospace)
        self.setFont(font)
        self.document().setDocumentMargin(4)
        self.setAccessibleName("Terminal")

    def terminal_size(self):
        metrics = self.fontMetrics()
        return (max(2, int((self.viewport().width() - 8) /
                           metrics.horizontalAdvance("M"))),
                max(2, int((self.viewport().height() - 8) / metrics.lineSpacing())))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit(*self.terminal_size())

    def paste(self):
        text = QApplication.clipboard().text().replace("\r\n", "\n").replace("\n", "\r")
        if text:
            self.input_received.emit(text)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setObjectName("terminalMenu")
        copy = menu.addAction("Copy", self.copy)
        copy.setEnabled(self.textCursor().hasSelection())
        menu.addAction("Paste", self.paste)
        menu.addAction("Select all", self.selectAll)
        menu.exec(event.globalPos())

    def keyPressEvent(self, event):
        modifiers = event.modifiers()
        control = bool(modifiers & Qt.ControlModifier)
        shift = bool(modifiers & Qt.ShiftModifier)
        if control and event.key() == Qt.Key_C and (shift or self.textCursor().hasSelection()):
            self.copy()
            return
        if event.matches(QKeySequence.Paste) or (control and shift and event.key() == Qt.Key_V):
            self.paste()
            return
        if shift and event.key() in (Qt.Key_PageUp, Qt.Key_PageDown):
            super().keyPressEvent(event)
            return
        sequences = {
            Qt.Key_Return: "\r", Qt.Key_Enter: "\r", Qt.Key_Backspace: "\x7f",
            Qt.Key_Tab: "\t", Qt.Key_Backtab: "\x1b[Z", Qt.Key_Escape: "\x1b",
            Qt.Key_Up: "\x1b[A", Qt.Key_Down: "\x1b[B",
            Qt.Key_Right: "\x1b[C", Qt.Key_Left: "\x1b[D",
            Qt.Key_Home: "\x1b[H", Qt.Key_End: "\x1b[F",
            Qt.Key_Insert: "\x1b[2~", Qt.Key_Delete: "\x1b[3~",
            Qt.Key_PageUp: "\x1b[5~", Qt.Key_PageDown: "\x1b[6~",
            Qt.Key_F1: "\x1bOP", Qt.Key_F2: "\x1bOQ", Qt.Key_F3: "\x1bOR",
            Qt.Key_F4: "\x1bOS", Qt.Key_F5: "\x1b[15~", Qt.Key_F6: "\x1b[17~",
            Qt.Key_F7: "\x1b[18~", Qt.Key_F8: "\x1b[19~", Qt.Key_F9: "\x1b[20~",
            Qt.Key_F10: "\x1b[21~", Qt.Key_F11: "\x1b[23~", Qt.Key_F12: "\x1b[24~",
        }
        text = sequences.get(event.key(), event.text())
        if control and Qt.Key_A <= event.key() <= Qt.Key_Z and not modifiers & Qt.AltModifier:
            text = chr(event.key() - Qt.Key_A + 1)
        elif (control or shift) and event.key() in (
                Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right, Qt.Key_Home, Qt.Key_End):
            text = f"\x1b[1;{1 + int(shift) + 4 * int(control)}{text[-1]}"
        elif modifiers & Qt.AltModifier and not control:
            text = "\x1b" + text
        if text:
            self.input_received.emit(text)
            self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
        event.accept()

    def inputMethodEvent(self, event):
        if event.commitString():
            self.input_received.emit(event.commitString())
        event.accept()


class TerminalView(QWidget):
    """A terminal emulator, rather than a new process for each command."""

    COLORS = dict(zip(
        ("black", "red", "green", "brown", "blue", "magenta", "cyan", "white",
         "brightblack", "brightred", "brightgreen", "brightbrown", "brightblue",
         "brightmagenta", "brightcyan", "brightwhite"),
        ("#181926", "#ed8796", "#a6da95", "#eed49f", "#8aadf4", "#c6a0f6",
         "#8bd5ca", "#cad3f5", "#6e738d", "#f5a9b8", "#bce6af", "#f5e0b5",
         "#b7bdf8", "#d5b8ff", "#a6e3db", "#ffffff")))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("terminalPage")
        self.directory = Path(os.environ.get("USERPROFILE") or Path.home())
        self.session = None
        self._disposed = False
        self.display = TerminalDisplay(self)
        self.screen = TerminalScreen(self.send_input)
        self.stream = pyte.Stream(self.screen)
        self.status = QLabel(str(self.directory))
        self.status.setObjectName("terminalStatus")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 12)
        layout.addWidget(self.display, 1)
        self.display.input_received.connect(self.send_input)
        self.display.resized.connect(self.resize_terminal)
        self.render_timer = QTimer(self)
        self.render_timer.setSingleShot(True)
        self.render_timer.setInterval(33)
        self.render_timer.timeout.connect(self.render_screen)
        self.setFocusProxy(self.display)
        QTimer.singleShot(0, self.start_session)

    @Slot()
    def start_session(self):
        if self._disposed:
            return
        if self.session is not None and self.session.isRunning():
            return
        self.screen.reset()
        self.stream = pyte.Stream(self.screen)
        self.status.setText(str(self.directory))
        self.session = TerminalSession(self.directory, *self.display.terminal_size())
        self.session.output.connect(self.receive_output)
        self.session.failed.connect(self.show_error)
        self.session.exited.connect(self.session_exited)
        self.destroyed.connect(self.session.stop)
        self.session.finished.connect(self.session.deleteLater)
        self.resize_terminal(*self.display.terminal_size())
        self.session.start()
        self.display.setFocus()

    def dispose(self):
        """Stop promptly on panel removal, before Qt's deferred deletion."""
        self._disposed = True
        self.render_timer.stop()
        if self.session is not None:
            self.session.stop()

    @Slot(str)
    def send_input(self, text):
        if self.session is not None:
            self.session.write(text)

    @Slot(str)
    def receive_output(self, text):
        self.stream.feed(text)
        if not self.render_timer.isActive():
            self.render_timer.start()

    @Slot(str)
    def show_error(self, message):
        self.status.setText(f"Terminal error: {message}")
        self.status.setToolTip(message)

    @Slot(int)
    def session_exited(self, code):
        if not self.status.text().startswith("Terminal error:"):
            self.status.setText(f"Session ended ({code})")
        self.session = None

    @Slot(int, int)
    def resize_terminal(self, columns, rows):
        self.screen.resize(lines=rows, columns=columns)
        if self.session is not None:
            self.session.resize_terminal(columns, rows)
        self.render_timer.start()

    def _format(self, char):
        def color(name, default):
            return QColor(default if name == "default" else
                          self.COLORS.get(name, f"#{name}"))
        foreground = color(char.fg, "#cad3f5")
        background = color(char.bg, "#181926")
        if char.reverse:
            foreground, background = background, foreground
        result = QTextCharFormat()
        result.setForeground(foreground)
        result.setBackground(background)
        result.setFontWeight(QFont.Bold if char.bold else QFont.Normal)
        result.setFontItalic(char.italics)
        result.setFontUnderline(char.underscore)
        result.setFontStrikeOut(char.strikethrough)
        return result

    def render_screen(self):
        scrollbar = self.display.verticalScrollBar()
        follow = scrollbar.value() >= scrollbar.maximum() - 1
        position = scrollbar.value()
        selection = self.display.textCursor()
        anchor, end = selection.anchor(), selection.position()
        self.display.setUpdatesEnabled(False)
        cursor = QTextCursor(self.display.document())
        cursor.beginEditBlock()
        cursor.select(QTextCursor.Document)
        cursor.removeSelectedText()
        lines = list(self.screen.history.top) + [
            self.screen.buffer[row] for row in range(self.screen.lines)]
        formats = {}
        for index, line in enumerate(lines):
            if index:
                cursor.insertBlock()
            run, previous = "", None
            for column in range(self.screen.columns):
                char = line[column]
                style = char[1:]
                if previous is not None and style != previous:
                    cursor.insertText(run, formats[previous])
                    run = ""
                if style not in formats:
                    formats[style] = self._format(char)
                previous = style
                run += char.data
            if run:
                cursor.insertText(run, formats[previous])
        cursor.endEditBlock()
        maximum = self.display.document().characterCount() - 1
        selection.setPosition(min(anchor, maximum))
        selection.setPosition(min(end, maximum), QTextCursor.KeepAnchor)
        self.display.setTextCursor(selection)
        extras = []
        if not self.screen.cursor.hidden:
            caret = QTextEdit.ExtraSelection()
            row = len(self.screen.history.top) + self.screen.cursor.y
            caret.cursor = QTextCursor(self.display.document().findBlockByNumber(row))
            prefix = "".join(self.screen.buffer[self.screen.cursor.y][col].data
                             for col in range(self.screen.cursor.x))
            caret.cursor.movePosition(QTextCursor.Right, QTextCursor.MoveAnchor,
                                      len(prefix.encode("utf-16-le")) // 2)
            caret.cursor.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor)
            caret.format.setBackground(QColor("#cad3f5"))
            caret.format.setForeground(QColor("#181926"))
            extras.append(caret)
        self.display.setExtraSelections(extras)
        scrollbar.setValue(scrollbar.maximum() if follow else position)
        self.display.setUpdatesEnabled(True)
