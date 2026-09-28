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
from src.init.identity import get_assistant_name

import os
import base64
import shlex
from collections import deque
import queue
import select
import shutil
import signal
import subprocess
import sys
import threading
import time
import re
from dataclasses import dataclass, field
from pathlib import Path

import pyte
from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont, QKeySequence, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import *


@dataclass(eq=False)
class TerminalRequest:
    argv: list[str]
    directory: str
    command: str
    timeout: int | None
    started: threading.Event = field(default_factory=threading.Event)
    completed: threading.Event = field(default_factory=threading.Event)
    result: dict | None = None
    panel_id: str | None = None
    output: str = ""
    output_length: int = 0
    error: str | None = None


class TerminalBridge(QObject):
    """Run assistant commands in real terminal panels on the GUI thread."""
    requested = Signal(object)
    cancel_requested = Signal(object)

    def __init__(self, parent):
        super().__init__(parent)
        self._lock = threading.RLock()
        self._pending = set()
        self._sessions = {}
        self._closed = False
        self.requested.connect(self._open, Qt.QueuedConnection)
        self.cancel_requested.connect(self._cancel, Qt.QueuedConnection)
        QApplication.instance().aboutToQuit.connect(self.shutdown)
        from .commands import set_terminal_executor
        set_terminal_executor(self.execute)

    def execute(self, argv, directory, command, timeout):
        if QThread.currentThread() == self.thread():
            raise RuntimeError("Terminal commands must be requested from the assistant worker")
        request = TerminalRequest(argv, directory, command, timeout)
        with self._lock:
            if self._closed:
                raise RuntimeError(f"{get_assistant_name()}'s terminal is shutting down")
            self._pending.add(request)
        self.requested.emit(request)
        if not request.started.wait(15):
            with self._lock:
                if not request.started.is_set():
                    self._complete(request, status="error", error="Terminal did not open; request cancelled")
                    self.cancel_requested.emit(request)
        if not request.completed.wait(None if timeout is None else timeout + 15):
            self._complete(request, status="timeout", error="Terminal command did not finish in time")
            self.cancel_requested.emit(request)
        return request.result

    def _complete(self, request, **result):
        with self._lock:
            if request.completed.is_set():
                return
            request.result = dict(result, terminal_panel_id=request.panel_id)
            self._pending.discard(request)
            request.started.set()
            request.completed.set()

    @Slot(object)
    def _open(self, request):
        with self._lock:
            if self._closed or request.completed.is_set():
                return
            view = None
            try:
                workspace = self.parent().workspace
                view = TerminalView(directory=request.directory, argv=request.argv,
                                    timeout=request.timeout, autostart=False)
                view.setProperty("workspaceViewKey", "terminal")
                request.panel_id = workspace.open_panel(title="Terminal", content=view)
                self.parent().restore_from_mascot()
                view.start_session(on_created=lambda session: self._watch_session(session, request))
                view.receive_output(request.command.replace("\n", "\r\n") + "\r\n")
                request.started.set()
            except Exception as error:
                if view is not None:
                    view.dispose()
                    if view.parentWidget() is None:
                        view.deleteLater()
                self._complete(request, status="error", error=str(error))

    def _watch_session(self, session, request):
        self._sessions[session] = request
        session.output.connect(self._receive_output)
        session.failed.connect(self._failed)
        session.exited.connect(self._exited)

    @Slot(str)
    def _receive_output(self, text):
        request = self._sessions.get(self.sender())
        if request is not None:
            request.output_length += len(text)
            request.output = (request.output + text)[-32000:]

    @Slot(str)
    def _failed(self, error):
        request = self._sessions.get(self.sender())
        if request is not None:
            request.error = error

    @Slot(int)
    def _exited(self, code):
        session = self.sender()
        request = self._sessions.pop(session, None)
        if request is None:
            return
        status = ("timeout" if session.timed_out else "error" if request.error else
                  "cancelled" if session.cancelled else
                  "completed" if code == 0 else "failed")
        output = re.sub(r"\x1b][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]",
                        "", request.output).replace("\r\n", "\n")
        self._complete(request, status=status, exit_code=code,
                       stdout=output, stderr="", output_streams_merged=True,
                       output_truncated=request.output_length > 32000,
                       **({"error": request.error} if request.error else {}))

    @Slot(object)
    def _cancel(self, request):
        for session, pending in tuple(self._sessions.items()):
            if pending is request:
                session.stop()

    @Slot()
    def shutdown(self):
        with self._lock:
            self._closed = True
            for request in tuple(self._pending):
                self._complete(request, status="cancelled", error=f"{get_assistant_name()}'s terminal was closed")
            for session in self._sessions:
                session.stop()


class TerminalSession(QThread):
    """Own the PTY off the GUI thread; all writes and resizes are queued."""

    output = Signal(str)
    ready = Signal()
    failed = Signal(str)
    exited = Signal(int)

    def __init__(self, directory: Path, columns=80, rows=24, *, argv=None, timeout=None):
        super().__init__(QApplication.instance())
        self.directory = directory
        self.columns, self.rows = columns, rows
        self.commands = queue.Queue()
        self.pid = None
        self.argv = argv
        self.timeout = timeout
        self.timed_out = False
        self.cancelled = False
        QApplication.instance().aboutToQuit.connect(self.shutdown)

    def write(self, text):
        self.commands.put(("write", text))

    def resize_terminal(self, columns, rows):
        self.commands.put(("resize", (columns, rows)))

    @Slot()
    def stop(self):
        self.cancelled = True
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
                argv = self.argv
                if argv is None:
                    shell = shutil.which("pwsh.exe") or str(
                        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
                        / "PowerShell" / "7" / "pwsh.exe")
                    if not Path(shell).is_file():
                        shell = shutil.which("powershell.exe")
                    if shell is None:
                        raise FileNotFoundError("PowerShell is unavailable")
                    argv = [shell, "-NoLogo", "-NoProfile"]
                if getattr(sys, "frozen", False):
                    executable, arguments = argv[0], argv[1:]
                else:
                    python = Path(sys.executable)
                    if python.name.lower() == "pythonw.exe":
                        python = python.with_name("python.exe")
                    bootstrap = Path(__file__).with_name("desktop") / "terminal_shell.py"
                    executable, arguments = str(python), [str(bootstrap), *argv]
                process.spawn(executable,
                              cmdline=" " + subprocess.list2cmdline(arguments),
                              cwd=str(self.directory),
                              env="\0".join(f"{k}={v}" for k, v in environment.items()) + "\0")
            else:
                from ptyprocess import PtyProcessUnicode
                shell = os.environ.get("SHELL") or shutil.which("sh") or "/bin/sh"
                process = PtyProcessUnicode.spawn(
                    self.argv or [shell, "-i"], cwd=str(self.directory), env=environment,
                    dimensions=(self.rows, self.columns))
            self.pid = process.pid
            self.ready.emit()
            started = time.monotonic()
            while not self.isInterruptionRequested():
                if self.timeout is not None and time.monotonic() - started >= self.timeout:
                    self.timed_out = True
                    break
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
                    data = process.read(32768)
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
            if process is not None:
                # ConPTY can close its output pipe just before the bootstrap
                # process exits. Wait for its real status instead of guessing.
                deadline = time.monotonic() + 5
                while (process.isalive() and not self.isInterruptionRequested()
                       and time.monotonic() < deadline):
                    self.msleep(10)
                code = (process.get_exitstatus() if os.name == "nt" else process.exitstatus)
                exit_code = code if code is not None else -1
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

    def __init__(self, send, *, preserve_output=False):
        self.send = send
        super().__init__(80, 24, history=1000)
        if preserve_output:
            self.history = self.history._replace(top=deque(), bottom=deque())

    def write_process_input(self, data):
        self.send(data)


class TerminalDisplay(QPlainTextEdit):
    input_received = Signal(str)
    resized = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("terminalOutput")
        self.setFrameShape(QFrame.NoFrame)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.viewport().setAutoFillBackground(False)
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

    def __init__(self, parent=None, *, directory=None, argv=None, timeout=None, autostart=True,
                 command=None, preserve_output=False):
        super().__init__(parent)
        self.setObjectName("terminalPage")
        self.directory = Path(directory or os.environ.get("USERPROFILE") or Path.home())
        self.argv = argv
        self.timeout = timeout
        self.session = None
        self._disposed = False
        self._pending_command = command
        self.output_history = [] if preserve_output else None
        self.display = TerminalDisplay(self)
        self.screen = TerminalScreen(self.send_input, preserve_output=preserve_output)
        self.stream = pyte.Stream(self.screen)
        self.status = QLabel(str(self.directory))
        self.status.setObjectName("terminalStatus")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 12)
        layout.addWidget(self.display, 1)
        layout.addWidget(self.status)
        self.display.input_received.connect(self.send_input)
        self.display.resized.connect(self.resize_terminal)
        self.render_timer = QTimer(self)
        self.render_timer.setSingleShot(True)
        self.render_timer.setInterval(33)
        self.render_timer.timeout.connect(self.render_screen)
        self.setFocusProxy(self.display)
        if command is not None:
            self.receive_output(command.replace("\r\n", "\n").replace("\n", "\r\n") + "\r\n")
        if autostart:
            QTimer.singleShot(0, self.start_session)

    @Slot()
    def start_session(self, *, on_created=None):
        if self._disposed:
            return
        if self.session is not None and self.session.isRunning():
            return
        if self._pending_command is None:
            self.screen.reset()
        self.stream = pyte.Stream(self.screen)
        self.status.setText(str(self.directory))
        self.session = TerminalSession(self.directory, *self.display.terminal_size(),
                                       argv=self.argv, timeout=self.timeout)
        self.session.output.connect(self.receive_output)
        self.session.ready.connect(self._submit_command)
        self.session.failed.connect(self.show_error)
        self.session.exited.connect(self.session_exited)
        self.destroyed.connect(self.session.stop)
        self.session.finished.connect(self.session.deleteLater)
        self.resize_terminal(*self.display.terminal_size())
        if on_created is not None:
            on_created(self.session)
        self.session.start()
        if self.isVisible():
            self.display.setFocus()

    def dispose(self):
        """Stop promptly on panel removal, before Qt's deferred deletion."""
        self._disposed = True
        self._pending_command = None
        self.render_timer.stop()
        if self.session is not None:
            self.session.stop()

    @Slot(str)
    def send_input(self, text):
        if self.session is not None:
            self.session.write(text)

    @Slot()
    def _submit_command(self):
        if self._disposed or self.session is None or self._pending_command is None:
            return
        command, self._pending_command = self._pending_command, None
        if os.name == "nt":
            encoded = base64.b64encode(command.encode("utf-8")).decode("ascii")
            text = ". ([scriptblock]::Create([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + encoded + "'))))"
        else:
            text = "eval " + shlex.quote(command)
        self.send_input(text + "\r")

    @Slot(str)
    def receive_output(self, text):
        if self.output_history is not None:
            self.output_history.append(text)
        self.stream.feed(text)
        if not self.render_timer.isActive():
            self.render_timer.start()

    @Slot(str)
    def show_error(self, message):
        self.status.setText(f"Terminal error: {message}")
        self.status.setToolTip(message)
        self.receive_output(f"\r\nTerminal error: {message}\r\n")

    @Slot(int)
    def session_exited(self, code):
        if not self.status.text().startswith("Terminal error:"):
            timed_out = self.session is not None and self.session.timed_out
            self.status.setText("Command timed out" if timed_out else f"Session ended ({code})")
        self.session = None

    @Slot(int, int)
    def resize_terminal(self, columns, rows):
        self.screen.resize(lines=rows, columns=columns)
        if self.session is not None:
            self.session.resize_terminal(columns, rows)
        self.render_timer.start()

    def _format(self, char):
        def color(name, default):
            return QColor(
                default if name == "default"
                else self.COLORS.get(name, f"#{name}"))

        foreground = color(char.fg, "#cad3f5")
        result = QTextCharFormat()

        if char.bg != "default":
            background = color(char.bg, "#181926")
            result.setBackground(background)
        else:
            background = QColor("#24273a")
            result.clearBackground()

        if char.reverse:
            result.setForeground(background)
            result.setBackground(foreground)
        else:
            result.setForeground(foreground)

        result.setFontWeight(
            QFont.Bold if char.bold else QFont.Normal
        )
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
