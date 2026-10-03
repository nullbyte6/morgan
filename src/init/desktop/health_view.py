#  Copyright (c) 2026 Diego.
#
#  SPDX-License-Identifier: GPL-3.0-or-later
#
#  This file is part of morgan.
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
"""The health workspace view: one card per check, refreshed in the background."""
import threading
from datetime import datetime

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from src.init.health import Check, collect, report
from src.init.lang import tr

COPIED_MS = 1200
GLYPHS = {"ok": "\U000f05e0", "warning": "\U000f0026", "error": "\U000f0159"}


def _label(text: str, name: str, wrap: bool = True) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


class CheckCard(QFrame):
    """One area of the health report: its state, a summary and the measured details."""

    def __init__(self, check: Check, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("novaRow")
        marker = _label(GLYPHS.get(check.status, GLYPHS["error"]), "healthStatus", wrap=False)
        marker.setProperty("status", check.status)
        marker.setFixedWidth(24)
        marker.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        column = QVBoxLayout()
        column.setSpacing(3)
        column.addWidget(_label(tr(f"health.area.{check.area}"), "novaRowCaption", wrap=False))
        column.addWidget(_label(check.summary, "novaRowTitle"))
        for detail in check.details:
            column.addWidget(_label(detail, "novaRowNotes"))
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 13, 16, 13)
        row.setSpacing(14)
        row.addWidget(marker, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(column, 1)


class HealthView(QWidget):
    """Ollama, the main model, the GPU and PyTorch build and the voice service at a glance."""

    collected = Signal(object)

    def __init__(self, parent: QWidget | None = None, checks: list[Check] | None = None):
        super().__init__(parent)
        self.setObjectName("healthView")
        self.setProperty("workspaceEmpty", False)
        self._running = False
        self._checks: list[Check] = []
        self._checked_at = datetime.now()

        self.title = QLabel()
        self.title.setObjectName("novaTitle")
        self.tagline = QLabel()
        self.tagline.setObjectName("novaTagline")
        for label in (self.title, self.tagline):
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        heading = QVBoxLayout()
        heading.setSpacing(3)
        heading.addWidget(self.title)
        heading.addWidget(self.tagline)
        self.refresh_button = QPushButton()
        self.refresh_button.setObjectName("novaTodayButton")
        self.refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_button = QPushButton()
        self.copy_button.setObjectName("novaTodayButton")
        self.copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_button.setEnabled(False)
        self.copy_reset = QTimer(self)
        self.copy_reset.setSingleShot(True)
        self.copy_reset.setInterval(COPIED_MS)
        self.copy_reset.timeout.connect(self.refresh_language)
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addLayout(heading, 1)
        top.addWidget(self.copy_button, 0, Qt.AlignmentFlag.AlignTop)
        top.addWidget(self.refresh_button, 0, Qt.AlignmentFlag.AlignTop)

        self._rows = QVBoxLayout()
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(8)
        self._rows.addStretch(1)
        body = QWidget()
        body.setObjectName("novaEntryBody")
        body.setLayout(self._rows)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("novaScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.setWidget(body)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(18)
        layout.addLayout(top)
        layout.addWidget(self.scroll, 1)

        self.refresh_button.clicked.connect(self.refresh)
        self.copy_button.clicked.connect(self._copy)
        self.collected.connect(self._show, Qt.ConnectionType.QueuedConnection)
        self.refresh_language()
        if checks is None:
            self.refresh()
        else:
            self._show(checks)

    def minimumSizeHint(self) -> QSize:
        return QSize(360, 260)

    def refresh_language(self) -> None:
        self.title.setText(tr("health.title"))
        self.tagline.setText(tr("health.tagline"))
        self.refresh_button.setText(tr("health.checking") if self._running else tr("health.refresh"))
        if not self.copy_reset.isActive():
            self.copy_button.setText(tr("health.copy"))
        self.copy_button.setToolTip(tr("health.copy_tooltip"))

    def _copy(self) -> None:
        QApplication.clipboard().setText(report(self._checks, self._checked_at))
        self.copy_button.setText(tr("nova.diary.copied"))
        self.copy_reset.start()

    def refresh(self) -> None:
        if self._running:
            return
        self._running = True
        self.refresh_button.setEnabled(False)
        self.refresh_language()
        threading.Thread(target=self._collect, name="health-check", daemon=True).start()

    def _collect(self) -> None:
        checks = collect()
        try:
            self.collected.emit(checks)
        except RuntimeError:
            pass

    def _show(self, checks: list[Check]) -> None:
        self._running = False
        self._checks = checks
        self._checked_at = datetime.now()
        self.refresh_button.setEnabled(True)
        self.copy_button.setEnabled(True)
        self.refresh_language()
        while self._rows.count() > 1:
            widget = self._rows.takeAt(0).widget()
            widget.setParent(None)
            widget.deleteLater()
        for check in checks:
            self._rows.insertWidget(self._rows.count() - 1, CheckCard(check))
        self._rows.insertWidget(self._rows.count() - 1,
                                _label(tr("health.checked_at", time=f"{self._checked_at:%H:%M:%S}"),
                                       "novaRowCaption", wrap=False))
