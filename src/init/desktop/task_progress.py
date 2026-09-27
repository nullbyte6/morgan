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

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import *

from src.init.lang import tr

class TaskProgressPill(QWidget):
    """A dismissible view of the shared task presentation."""
    def __init__(self, presentation, parent=None):
        super().__init__(parent)
        self.setObjectName("taskProgressHost")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.view = presentation.view
        self.dismissed = False
        presentation.changed.connect(self.on_view)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(0)
        row.setAlignment(Qt.AlignLeft | Qt.AlignTop)
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

    @property
    def state(self):
        return self.view.state

    def sizeHint(self):
        size = super().sizeHint()
        size.setWidth(self.fontMetrics().averageCharWidth() * 48)
        return size

    @Slot(object)
    def on_view(self, view):
        if view.turn_id != self.view.turn_id:
            self.dismissed = False
            self.hide()
        self.view = view
        self._render()
        if (view.started >= 2 or view.lifecycle == "blocked") and not self.dismissed:
            self.show()

    @Slot()
    def dismiss(self):
        self.dismissed = True
        self.setVisible(False)

    def refresh_language(self, _language=None):
        self.setMaximumWidth(self.fontMetrics().averageCharWidth() * 48)
        close = tr("task_progress.hide")
        self.close_button.setToolTip(close)
        self.close_button.setAccessibleName(close)
        self.bar.setToolTip(tr("task_progress.progress_hint"))
        self._render()

    def _render(self):
        title = self.view.title or tr("task_progress.pending_title")
        self.title.setToolTip(title)
        self.title.setAccessibleName(title)
        self.title.setText(self.title.fontMetrics().elidedText(
            title, Qt.ElideRight, max(1, self.title.width())))
        count = tr("task_progress.step_count", completed=self.view.completed, total=self.view.started)
        if self.state == "running":
            detail = (tr("task_progress.executing", step=self.view.completed + 1)
                      if self.view.completed < self.view.started else "")
        elif self.state == "waiting":
            detail = tr("activity." + self.view.activity[0])
        else:
            detail = tr("task_progress." + self.state)
        self.step.setText(tr("task_progress.summary", detail=detail, count=count))
        subtitle = ""
        if self.view.step_detail:
            kind, tool, subject, step = self.view.step_detail
            detail = tr("task_progress.step_" + kind, tool=tool)
            if subject and kind != "checkpoint":
                detail += "\n" + subject
            subtitle = tr("task_progress.step_detail", step=step, detail=detail)
        self.subtitle.setText(subtitle)
        self.subtitle.setVisible(self.view.step_detail is not None)
        self.bar.setRange(0, max(1, self.view.started))
        self.bar.setValue(self.view.completed)
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
        self.raise_()
        self._render()

    def eventFilter(self, watched, event):
        if watched is self.pill and event.type() == event.Type.Resize:
            self._fit_height()
        return super().eventFilter(watched, event)
