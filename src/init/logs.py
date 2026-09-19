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

import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (QHBoxLayout,
                               QLabel, QPushButton, QTextEdit, QVBoxLayout,
                               QWidget)


class LogView(QWidget):
    """What Arlo and the user are talking about."""
    def __init__(self, log_dir: Path, parent=None):
        super().__init__(parent)
        self.log_dir = log_dir
        self.current_date = datetime.date.today()
        self.last_content = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 12)
        layout.setSpacing(8)
        layout.setSpacing(12)

        header = QHBoxLayout()
        self.title = QLabel(self.current_date.strftime("%Y/%m/%d"))
        self.title.setObjectName("logTitle")
        header.addWidget(self.title)
        header.addStretch()

        self.refresh_button = QPushButton("󰑓")
        self.refresh_button.setObjectName("refresh")
        self.refresh_button.setFixedSize(48, 48)
        self.refresh_button.clicked.connect(self.refresh)
        header.addWidget(self.refresh_button)
        header.setContentsMargins(-20, 0, -20, 0)
        layout.addLayout(header)

        self.viewer = QTextEdit()
        self.viewer.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.viewer.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.viewer.setObjectName("logViewer")
        self.viewer.setReadOnly(True)
        layout.addWidget(self.viewer, 0)

        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.refresh)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def refresh(self):
        today = datetime.date.today()
        if today != self.current_date:
            self.current_date = today
            self.last_content = None
            self.title.setText(today.strftime("%Y/%m/%d"))

        path = self.log_dir / f"{today:%Y-%m-%d}.md"
        try:
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            content = ""
        except OSError as error:
            content = str(error)

        if content == self.last_content:
            return

        self.last_content = content

        scrollbar = self.viewer.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 20
        old_position = scrollbar.value()

        self.viewer.setMarkdown(content)

        if at_bottom:
            cursor = self.viewer.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.viewer.setTextCursor(cursor)
            self.viewer.ensureCursorVisible()
        else:
            scrollbar.setValue(old_position)