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
"""The update workspace strip: downloads a release's installer with a progress bar."""
import logging
import threading
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from src.init.lang import tr
from src.init.updates import Release, UpdateCancelled, download

HEIGHT = 150


def _megabytes(size: int) -> str:
    return f"{size / 1024 ** 2:.1f}"


class UpdateView(QWidget):
    """Download progress of one release, then the installing state until Morgan closes."""

    progressed = Signal(int, int)
    downloaded = Signal(object)
    failed = Signal(str)
    ready = Signal(object)

    def __init__(self, release: Release, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("updateView")
        self.setProperty("workspaceEmpty", False)
        self.release = release
        self._cancel = threading.Event()

        self.title = QLabel()
        self.title.setObjectName("taskProgressTitle")
        self.bar = QProgressBar()
        self.bar.setObjectName("taskProgressBar")
        self.bar.setTextVisible(False)
        self.bar.setProperty("state", "running")
        self.detail = QLabel()
        self.detail.setObjectName("taskProgressSubtitle")
        self.cancel_button = QPushButton()
        self.cancel_button.setObjectName("novaTodayButton")
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(self.title, 1)
        top.addWidget(self.cancel_button, 0, Qt.AlignmentFlag.AlignVCenter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 8, 20, 10)
        layout.setSpacing(8)
        layout.addLayout(top)
        layout.addWidget(self.bar)
        layout.addWidget(self.detail)
        layout.addStretch(1)

        self.progressed.connect(self._show_progress, Qt.ConnectionType.QueuedConnection)
        self.downloaded.connect(self._install, Qt.ConnectionType.QueuedConnection)
        self.failed.connect(self._show_failure, Qt.ConnectionType.QueuedConnection)
        self.cancel_button.clicked.connect(self.cancel)
        self.refresh_language()
        threading.Thread(target=self._download, name="update-download", daemon=True).start()

    def minimumSizeHint(self) -> QSize:
        return QSize(280, 72)

    def refresh_language(self) -> None:
        self.title.setText(tr("update.downloading", version=self.release.version))
        self.cancel_button.setText(tr("update.cancel"))

    def cancel(self) -> None:
        self._cancel.set()

    def dispose(self) -> None:
        self._cancel.set()

    def _download(self) -> None:
        try:
            path = download(self.release, self._emit_progress, self._cancel)
        except UpdateCancelled:
            self._emit(self.failed, tr("update.cancelled"))
            return
        except Exception as error:
            logging.getLogger("assistant.update").exception("The update could not be downloaded")
            self._emit(self.failed, tr("ui.error", error=error))
            return
        self._emit(self.downloaded, path)

    def _emit_progress(self, received: int, total: int) -> None:
        self._emit(self.progressed, received, total)

    @staticmethod
    def _emit(signal, *values) -> None:
        try:
            signal.emit(*values)
        except RuntimeError:
            pass

    def _show_progress(self, received: int, total: int) -> None:
        if total:
            self.bar.setRange(0, 1000)
            self.bar.setValue(min(1000, received * 1000 // total))
            self.detail.setText(tr("update.progress", received=_megabytes(received), total=_megabytes(total),
                                   percent=received * 100 // total))
        else:
            self.bar.setRange(0, 0)
            self.detail.setText(tr("update.progress_unknown", received=_megabytes(received)))

    def _install(self, path: Path) -> None:
        self.cancel_button.setEnabled(False)
        self.title.setText(tr("update.installing", version=self.release.version))
        self.detail.setText(tr("update.restarting"))
        self.bar.setRange(0, 0)
        self.ready.emit(path)

    def _show_failure(self, message: str) -> None:
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.bar.setProperty("state", "error")
        self.bar.style().unpolish(self.bar)
        self.bar.style().polish(self.bar)
        self.title.setText(tr("update.failed", version=self.release.version))
        self.detail.setText(message)
        self.cancel_button.hide()
