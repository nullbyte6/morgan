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

"""Non-blocking attachment selection and removable composer chips."""
from dataclasses import replace

from PySide6.QtCore import Qt, QObject, QRunnable, QThreadPool, Signal
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QScrollArea, QVBoxLayout, QWidget, QSizePolicy)

from .attachments import Attachment, inspect_attachment, normalized_path
from .lang import tr


class ValidationSignals(QObject):
    finished = Signal(object)


class ValidateAttachment(QRunnable):
    def __init__(self, item, limits):
        super().__init__()
        self.item, self.limits = item, limits
        self.signals = ValidationSignals()

    def run(self):
        try:
            result = inspect_attachment(self.item, self.limits)
        except Exception as error:
            result = replace(self.item, status="error", error=str(error))
        self.signals.finished.emit(result)


class AttachmentTray(QScrollArea):
    changed = Signal()

    def __init__(self, limits, parent=None):
        super().__init__(parent)
        self.limits = limits
        self.items = {}
        self.jobs = {}
        self.setObjectName("attachmentTray")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Fixed)

        self.content = QWidget()

        self.grid = QGridLayout(self.content)
        self.grid.setContentsMargins(0, 4, 0, 4)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(8)

        for column in range(4):
            self.grid.setColumnStretch(column, 1)

        self.setWidget(self.content)

        self.setFixedHeight(80)
        self.hide()

    def choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, tr("ui.attach_files"))
        self.add_files(paths)

    def add_files(self, paths):
        known = {normalized_path(a.path) for a in self.items.values()}
        for path in paths:
            if normalized_path(path) in known:
                continue
            if len(self.items) >= self.limits["max_files"]:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, tr("ui.attach_files"),
                                    tr("ui.attachment_count", count=self.limits["max_files"]))
                break
            known.add(normalized_path(path))
            item = Attachment.pending(path)
            self.items[item.id] = item
            job = ValidateAttachment(item, dict(self.limits))
            job.signals.finished.connect(self.validated)
            self.jobs[item.id] = job
            QThreadPool.globalInstance().start(job)
        self.refresh()

    def validated(self, item):
        self.jobs.pop(item.id, None)
        if item.id not in self.items:
            return
        if any(a.id != item.id and normalized_path(a.path) == normalized_path(item.path)
               and a.status == "ready" for a in self.items.values()):
            self.items.pop(item.id)
        else:
            self.items[item.id] = item
        self.refresh()

    def remove(self, item_id):
        self.items.pop(item_id, None)
        self.refresh()

    def clear(self):
        self.items.clear()
        self.refresh()

    @property
    def can_send(self):
        return (all(a.status == "ready" for a in self.items.values()) and
                sum(a.size for a in self.items.values()) <= self.limits["max_total_bytes"])

    def snapshot(self):
        return tuple(self.items.values())

    def refresh(self):
        while self.grid.count():
            layout_item = self.grid.takeAt(0)
            widget = layout_item.widget()

            if widget is not None:
                widget.hide()
                widget.deleteLater()

        over_limit = sum(a.size for a in self.items.values()) > self.limits["max_total_bytes"]
        for index, item in enumerate(self.items.values()):
            chip = QFrame()
            chip.setObjectName("attachmentChip")

            chip.setMinimumWidth(0)
            chip.setSizePolicy(
                QSizePolicy.Expanding,
                QSizePolicy.Fixed,
            )

            row = QHBoxLayout(chip)
            row.setContentsMargins(10, 6, 8, 6)
            icon = QLabel({"image": "\uf1c5", "pdf": "\uf1c1", "text": "\uf1c9"}.get(item.kind, "\uf15b"))
            row.addWidget(icon)
            labels = QVBoxLayout()
            labels.setSpacing(2)
            name = QLabel()
            name.setTextFormat(Qt.PlainText)

            name.setText(item.name)
            name.setMinimumWidth(0)
            name.setSizePolicy(
                QSizePolicy.Ignored,
                QSizePolicy.Preferred,
            )
            name.setToolTip(item.name)

            name.setToolTip(item.name)
            labels.addWidget(name)
            detail = QLabel()
            detail.setObjectName("attachmentDetail")
            detail.setTextFormat(Qt.PlainText)
            if item.status == "pending":
                secondary = tr("ui.attachment_checking")
            elif item.error or over_limit:
                secondary = tr("ui.attachment_error")
                chip.setToolTip(item.error or tr("ui.attachment_total"))
            else:
                secondary = f"{item.extension.upper().lstrip('.') or 'TEXT'} · {item.size / 1024:.1f} KB"
            detail.setText(secondary)
            labels.addWidget(detail)
            row.addLayout(labels, 1)
            remove = QPushButton("×")
            remove.setObjectName("removeAttachment")
            remove.setFixedSize(24, 24)
            remove.setToolTip(tr("ui.remove_attachment", name=item.name))
            remove.setAccessibleName(remove.toolTip())
            remove.clicked.connect(lambda checked=False, item_id=item.id: self.remove(item_id))
            row.addWidget(remove)
            grid_row, grid_column = divmod(index, 4)
            self.grid.addWidget(chip, grid_row, grid_column)

        count = len(self.items)
        rows = (count + 3) // 4

        chip_height = 72
        vertical_spacing = self.grid.verticalSpacing()
        top, bottom = 4, 4

        height = (top + bottom + rows * chip_height + max(0, rows - 1) *
                  vertical_spacing)

        self.setFixedHeight(height if rows else 0)

        self.setVisible(bool(self.items))
        self.changed.emit()
