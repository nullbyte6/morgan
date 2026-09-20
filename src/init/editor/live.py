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
from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import Qt, QRect, QSize, QTimer

from PySide6.QtGui import (
    QColor, QFont, QPainter, QPainterPath, QPen,
    QTextFormat)

from PySide6.QtWidgets import *

from src.init.editor.highlighter import PythonHighlighter

class CodeEditor(QPlainTextEdit):
    """Native code editor with line numbers and file operations."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.file_path: Path | None = None
        font = QFont("JetBrainsMono Nerd Font Mono", 11)
        font.setStyleHint(QFont.Monospace)
        self.setFont(font)

        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setTabStopDistance(
            self.fontMetrics().horizontalAdvance(" ") * 4)

        self.setObjectName("codeEditor")
        self.highlighter: PythonHighlighter | None = None

        self.line_area = LineNumberArea(self)
        self.blockCountChanged.connect(
            self.update_line_area_width)
        self.updateRequest.connect(
            self.update_line_area)
        self.cursorPositionChanged.connect(
            self.highlight_current_line)

        self.update_line_area_width()
        self.highlight_current_line()

    def configure_highlighter(self):
        """Configure syntax highlighting for the current file."""
        if self.highlighter is not None:
            self.highlighter.setDocument(None)
            self.highlighter = None

        if self.file_path is None:
            return

        suffix = self.file_path.suffix.lower()
        if suffix in {".py", ".pyw"}:
            self.highlighter = PythonHighlighter(self.document())

    def line_area_width(self):
        digits = len(str(max(1, self.blockCount())))
        return 16 + self.fontMetrics().horizontalAdvance("9") * digits

    def update_line_area_width(self, *_):
        self.setViewportMargins(
            self.line_area_width(), 0, 0, 0)

    def update_line_area(self, rect, dy):
        if dy:
            self.line_area.scroll(0, dy)
        else:
            self.line_area.update(
                0, rect.y(),
                self.line_area.width(), rect.height()
            )

        if rect.contains(self.viewport().rect()):
            self.update_line_area_width()

    def resizeEvent(self, event):
        super().resizeEvent(event)

        rect = self.contentsRect()
        self.line_area.setGeometry(
            QRect(
                rect.left(), rect.top(),
                self.line_area_width(), rect.height()))

    def paint_line_numbers(self, event):
        painter = QPainter(self.line_area)
        painter.fillRect(event.rect(), QColor("#171920"))

        block = self.firstVisibleBlock()
        number = block.blockNumber()

        top = round(
            self.blockBoundingGeometry(block)
            .translated(self.contentOffset()).top())

        while block.isValid() and top <= event.rect().bottom():
            height = round(self.blockBoundingRect(block).height())

            if block.isVisible() and top + height >= event.rect().top():
                painter.setPen(QColor("#737B8D"))

                painter.drawText(
                    0, top,
                    self.line_area.width() - 7, height,
                    Qt.AlignRight | Qt.AlignVCenter,
                    str(number + 1))

            block = block.next()
            number += 1
            top += height

        painter.end()

    def highlight_current_line(self):
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(QColor("#242836"))
        selection.format.setProperty(
            QTextFormat.FullWidthSelection, True)

        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()

        self.setExtraSelections([selection])

    def open_file(self, path: str | Path):
        path = Path(path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)

        content = path.read_text(encoding="utf-8-sig")
        self.setPlainText(content)
        self.file_path = path
        self.configure_highlighter()
        self.document().setModified(False)

    def save_file(self, path: str | Path | None = None):
        target = Path(path) if path else self.file_path
        if target is None:
            raise ValueError("No file selected")

        target = target.expanduser().resolve()
        if not target.parent.is_dir():
            raise FileNotFoundError(target.parent)

        import os
        import tempfile
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(self.toPlainText())

            if target.exists():
                os.chmod(temporary, target.stat().st_mode)
            temporary.replace(target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        
        self.file_path = target
        self.configure_highlighter()
        self.document().setModified(False)


class LineNumberArea(QWidget):
    def __init__(self, editor: CodeEditor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.line_area_width(), 0)

    def paintEvent(self, event):
        self.editor.paint_line_numbers(event)


class ArloRing(QWidget):
    """
    Hollow, audio-reactive representation of Arlo.
    Input: 15 normalized audio levels.
    Rendering: four layered, deformable circular outlines.
    """
    COLORS = (
        QColor(245, 247, 255, 240),
        QColor(165, 181, 255, 150),
        QColor(116, 133, 240, 95),
        QColor(96, 113, 205, 55),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("arloRing")
        self.setFixedSize(84, 84)

        self.levels = [0.0] * 15
        self.smoothed = [0.0] * 15

        self.amplitude = 0.0
        self.phase = 0.0

        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.animate)
        self.timer.start()

    def set_levels(self, levels):
        values = list(levels)[:15]
        self.levels = [
            max(0.0, min(1.0, float(level)))
            for level in values]

        self.levels.extend(
            [0.0] * (15 - len(self.levels)))

    def clear(self):
        self.levels = [0.0] * 15

    def animate(self):
        for index, level in enumerate(self.levels):
            speed = 1.40 if level > self.smoothed[index] else 0.75

            self.smoothed[index] += (
                level - self.smoothed[index]) * speed

        target = max(self.smoothed)
        speed = 1.20 if target > self.amplitude else 0.60
        self.amplitude += (
            target - self.amplitude) * speed

        if self.amplitude < 0.001:
            self.amplitude = 0.0

        self.phase += 0.035 + self.amplitude * 0.045
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        center_x = self.width() / 2
        center_y = self.height() / 2
        points = 180

        for layer, color in enumerate(self.COLORS):
            path = QPainterPath()
            base_radius = 24.0 + layer * 2.8
            for index in range(points + 1):
                t = index / points
                angle = t * math.tau
                position = t * 15
                band = min(14, int(position))
                next_band = (band + 1) % 15
                fraction = position - band

                level = (
                    self.smoothed[band] * (1.0 - fraction)
                    + self.smoothed[next_band] * fraction)

                wave = math.sin(
                    angle * 5.0
                    - self.phase * (1.0 + layer * 0.08)
                    + layer * 0.5)

                detail = math.sin(
                    angle * 9.0 + self.phase * 0.65) * 0.25

                energy = (
                    self.amplitude * 0.4
                    + level * 0.6)

                deformation = (
                    wave + detail) * energy * (5.0 + layer * 1.2)

                radius = base_radius + deformation
                x = center_x + math.cos(angle) * radius
                y = center_y + math.sin(angle) * radius

                if index == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)

            path.closeSubpath()
            pen = QPen(color)
            pen.setWidthF(2.0 if layer == 0 else 1.5)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

        painter.end()


class EditorView(QWidget):
    """
    Integrated editor page.
    Does not instantiate an Assistant or an AssistantWorker.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName("editorPage")
        self.tabs = QTabWidget()
        self.tabs.setObjectName("editorTabs")
        self.tabs.setTabsClosable(False)
        self.tabs.setDocumentMode(False)
        self.tabs.tabCloseRequested.connect(self.close_tab)

        self.open_button = QPushButton("Open")
        self.save_button = QPushButton("Save")

        self.open_button.clicked.connect(self.choose_file)
        self.save_button.clicked.connect(self.save_current)

        toolbar = QHBoxLayout()
        toolbar.addWidget(self.open_button)
        toolbar.addWidget(self.save_button)
        toolbar.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 12, 20, 20)
        layout.setSpacing(12)

        layout.addLayout(toolbar)
        layout.addWidget(self.tabs, 1)
        self.new_file()

    def current_editor(self) -> CodeEditor | None:
        widget = self.tabs.currentWidget()
        return widget if isinstance(widget, CodeEditor) else None

    def new_file(self):
        editor = CodeEditor(self)
        index = self.tabs.addTab(editor, "Untitled")
        close_button = QToolButton(self.tabs)
        close_button.setObjectName("editorTabClose")
        close_button.setText("×")
        close_button.setFixedSize(24, 24)
        close_button.setCursor(Qt.PointingHandCursor)

        close_button.clicked.connect(
            lambda checked=False, e=editor: self.close_editor(e))

        self.tabs.tabBar().setTabButton(
            index,
            QTabBar.RightSide,
            close_button)

        self.tabs.setCurrentIndex(index)

        editor.document().modificationChanged.connect(
            lambda modified, e=editor: self.update_tab(e))

        return editor

    def close_editor(self, editor: CodeEditor):
        index = self.tabs.indexOf(editor)

        if index >= 0:
            self.close_tab(index)

    def update_tab(self, editor: CodeEditor):
        index = self.tabs.indexOf(editor)

        if index < 0:
            return

        name = (
            editor.file_path.name
            if editor.file_path
            else "Untitled")

        if editor.document().isModified():
            name += " *"

        self.tabs.setTabText(index, name)

        if editor.file_path:
            self.tabs.setTabToolTip(index, str(editor.file_path))

    def open_file(self, path: str | Path):
        path = Path(path).expanduser().resolve()

        for index in range(self.tabs.count()):
            editor = self.tabs.widget(index)

            if isinstance(editor, CodeEditor):
                if editor.file_path == path:
                    self.tabs.setCurrentIndex(index)
                    return editor

        editor = self.new_file()

        try:
            editor.open_file(path)
        except (OSError, UnicodeError, ValueError):
            index = self.tabs.indexOf(editor)
            self.tabs.removeTab(index)
            editor.deleteLater()
            raise

        self.update_tab(editor)
        return editor

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open file",
            str(Path.cwd()),
            "All files (*)")

        if not path:
            return

        try:
            self.open_file(path)
        except (OSError, UnicodeError, ValueError) as error:
            QMessageBox.warning(
                self, "Arlo", str(error))

    def save_current(self):
        editor = self.current_editor()

        if editor is None:
            return False

        path = editor.file_path

        if path is None:
            filename, _ = QFileDialog.getSaveFileName(
                self,
                "Save file",
                str(Path.cwd()),
                "All files (*)")

            if not filename:
                return False

            path = Path(filename)

        try:
            editor.save_file(path)
        except (OSError, ValueError) as error:
            QMessageBox.warning(
                self, "Arlo", str(error))
            return False

        self.update_tab(editor)
        return True

    def close_tab(self, index):
        editor = self.tabs.widget(index)

        if not isinstance(editor, CodeEditor):
            return

        if editor.document().isModified():
            result = QMessageBox.question(
                self,
                "Unsaved changes",
                "Save changes before closing?",
                QMessageBox.Save
                | QMessageBox.Discard
                | QMessageBox.Cancel,
                QMessageBox.Cancel)

            if result == QMessageBox.Cancel:
                return

            if result == QMessageBox.Save:
                self.tabs.setCurrentIndex(index)

                if not self.save_current():
                    return

        self.tabs.removeTab(index)
        editor.deleteLater()

        if self.tabs.count() == 0:
            self.new_file()

    def set_audio_levels(self, levels):
        self.ring.set_levels(levels)

    def clear_audio(self):
        self.ring.clear()

    def set_status(self, text: str):
        self.status.setText(text)