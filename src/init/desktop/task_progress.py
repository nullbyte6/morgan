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

import json

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import *

from src.init.lang import tr

class TaskProgressPill(QWidget):
    """A dismissible view of the desktop's existing execution-phase signals."""
    def __init__(self, parent=None):
        super().__init__(parent)
        if parent is not None:
            parent.installEventFilter(self)
        self.setObjectName("taskProgressHost")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.turn_id = None
        self.started = 0
        self.completed = 0
        self.active = False
        self.dismissed = False
        self.state = "running"
        self.order_title = ""
        self.step_detail = None

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(0)
        self.pill = QFrame(self)
        self.pill.setObjectName("taskProgressPill")
        self.pill.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.pill.setMinimumWidth(0)
        self.pill.installEventFilter(self)
        body = QVBoxLayout(self.pill)
        body.setContentsMargins(16, 10, 14, 10)
        body.setSpacing(3)
        heading = QHBoxLayout()
        heading.setSpacing(12)
        self.title = QLabel()
        self.title.setObjectName("taskProgressTitle")
        self.title.setTextFormat(Qt.PlainText)
        self.title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.close_button = QPushButton("×")
        self.close_button.setObjectName("taskProgressClose")
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.clicked.connect(self.dismiss)
        heading.addWidget(self.title, 1)
        heading.addWidget(self.close_button)
        body.addLayout(heading)
        self.bar = QProgressBar()
        self.bar.setObjectName("taskProgressBar")
        self.bar.setTextVisible(False)
        body.addWidget(self.bar)
        self.subtitle = QLabel()
        self.subtitle.setObjectName("taskProgressSubtitle")
        self.subtitle.setTextFormat(Qt.PlainText)
        self.subtitle.setWordWrap(True)
        self.subtitle.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        body.addWidget(self.subtitle)
        self.step = QLabel()
        self.step.setObjectName("taskProgressStep")
        self.step.setTextFormat(Qt.PlainText)
        self.step.setWordWrap(True)
        self.step.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        body.addWidget(self.step)
        row.addWidget(self.pill, 1)
        row.addStretch(0)
        self.refresh_language()
        self.hide()

    def begin(self, turn_id, title):
        self.turn_id = turn_id
        words = str(title).split()
        self.order_title = " ".join(words) if len(words) in (3, 4) else ""
        self.started = self.completed = 0
        self.active = True
        self.dismissed = False
        self.state = "running"
        self.step_detail = None
        self.setVisible(False)
        self._render()

    @Slot(int, str)
    def on_phase(self, turn_id, phase):
        if turn_id != self.turn_id or not self.active:
            return
        if phase.startswith("title:"):
            words = phase[6:].split()
            if len(words) not in (3, 4):
                return
            self.order_title = " ".join(words)
        elif phase.startswith("step:"):
            try:
                detail = json.loads(phase[5:])
            except ValueError:
                return
            if (not isinstance(detail, dict)
                    or detail.get("kind") not in ("inspect", "execute", "verify", "checkpoint", "failed", "skipped")
                    or not isinstance(detail.get("tool"), str)):
                return
            subject = detail.get("subject", "")
            if not isinstance(subject, str):
                return
            self.step_detail = (detail["kind"], " ".join(detail["tool"].split())[:80]," ".join(subject.split())[:80], self.completed)
        elif phase == "executing":
            self.started += 1
            self.state = "running"
        elif phase == "processing" and self.completed < self.started:
            self.completed += 1
            self.state = "running"
        elif phase == "blocked":
            self.state = "error"
        elif phase == "waiting":
            self.state = "waiting"
        elif phase in {"interrupted", "cancelled", "limit_reached"}:
            self.state = "stopped"
        else:
            return
        self._render()
        if (self.started >= 2 or phase == "blocked") and not self.dismissed:
            self.setVisible(True)

    def awaiting_permission(self, turn_id, *, waiting=True):
        if turn_id == self.turn_id and self.active:
            self.state = "waiting" if waiting else "running"
            self._render()

    def finish(self, turn_id, *, interrupted=False, failed=False):
        if turn_id != self.turn_id or not self.active:
            return
        self.active = False
        self.state = ("stopped" if interrupted else "error" if failed or self.state == "error"
                      else self.state if self.state in {"waiting", "stopped"}
                      else "finished" if self.completed == self.started else "stopped")
        self._render()

    @Slot()
    def dismiss(self):
        self.dismissed = True
        self.setVisible(False)

    def refresh_language(self, _language=None):
        close = tr("task_progress.hide")
        self.close_button.setToolTip(close)
        self.close_button.setAccessibleName(close)
        self.bar.setToolTip(tr("task_progress.progress_hint"))
        self._render()

    def _render(self):
        title = self.order_title or tr("task_progress.pending_title")
        self.title.setToolTip(title)
        self.title.setAccessibleName(title)
        self.title.setText(self.title.fontMetrics().elidedText(
            title, Qt.ElideRight, max(1, self.title.width())))
        count = tr("task_progress.step_count", completed=self.completed, total=self.started)
        if self.state == "running":
            detail = (tr("task_progress.executing", step=self.completed + 1)
                      if self.completed < self.started else "")
        else:
            detail = tr("task_progress." + self.state)
        self.step.setText(tr("task_progress.summary", detail=detail, count=count))
        subtitle = ""
        if self.step_detail:
            kind, tool, subject, step = self.step_detail
            detail = tr("task_progress.step_" + kind, tool=tool)
            if subject and kind != "checkpoint":
                detail += "\n" + subject
            subtitle = tr("task_progress.step_detail", step=step, detail=detail)
        self.subtitle.setText(subtitle)
        self.subtitle.setVisible(self.step_detail is not None)
        self.bar.setRange(0, max(1, self.started))
        self.bar.setValue(self.completed)
        self.bar.setAccessibleName(self.step.text())
        for widget in (self.pill, self.bar):
            if widget.property("state") != self.state:
                widget.setProperty("state", self.state)
                widget.style().unpolish(widget)
                widget.style().polish(widget)
                widget.update()
        self._fit_height()

    def _fit_height(self):
        height = self.pill.layout().totalHeightForWidth(self.pill.width())
        if height >= 0 and (self.pill.minimumHeight() != height or self.pill.maximumHeight() != height):
            self.pill.setFixedHeight(height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._render()

    def showEvent(self, event):
        super().showEvent(event)
        self._render()

    def eventFilter(self, watched, event):
        if watched is self.pill and event.type() == event.Type.Resize:
            self._fit_height()
        if watched is self.parentWidget() and event.type() == event.Type.Resize:
            self.setGeometry(watched.rect())
            self.raise_()
        return super().eventFilter(watched, event)
