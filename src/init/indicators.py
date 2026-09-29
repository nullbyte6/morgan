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
import os
import subprocess
import time
from pathlib import Path

from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtWidgets import *

from src.init.config import PermissionMode
from src.init.lang import tr


class WorkingDirectory(QToolButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("directory")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAutoRaise(True)
        self.set_directory(Path.cwd())

    def set_directory(self, directory: Path | str):
        path = Path(directory).resolve()
        self.setText(f" {path.name or str(path)} ")
        self.setToolTip(str(path))


class GitBranchIndicator(QToolButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("branchIndicator")
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setAutoRaise(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._directory = None
        self._updated_at = 0.0
        self.set_directory(Path.cwd())

    def set_directory(self, directory: Path | str):
        path = str(Path(directory).resolve())
        now = time.monotonic()
        if path == self._directory and now - self._updated_at < 2:
            return
        self._directory = path
        self._updated_at = now
        branch = ""
        try:
            result = subprocess.run(
                ["git", "-C", path, "symbolic-ref", "--quiet", "--short", "HEAD"],
                capture_output=True, text=True, errors="replace", timeout=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if result.returncode == 0:
                branch = result.stdout.strip()
            elif result.returncode == 1:
                result = subprocess.run(
                    ["git", "-C", path, "rev-parse", "--short", "HEAD"],
                    capture_output=True, text=True, errors="replace", timeout=1,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                if result.returncode == 0:
                    branch = f"detached:{result.stdout.strip()}"
        except (OSError, subprocess.TimeoutExpired):
            pass
        self.setText(f"  {branch} ")
        self.setToolTip(branch)
        self.setVisible(bool(branch))


class ModelSelector(QComboBox):
    model_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("modelSelector")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        options = QListView(self)
        options.setMouseTracking(True)
        self.setView(options)
        options.setAutoFillBackground(True)
        options.viewport().setAutoFillBackground(True)
        arrow = QLabel("", self)
        arrow.setObjectName("languageDropdownArrow")
        arrow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        arrow.setFixedWidth(24)
        arrow_layout = QHBoxLayout(self)
        arrow_layout.setContentsMargins(0, 0, 4, 0)
        arrow_layout.addStretch()
        arrow_layout.addWidget(arrow)
        self.currentIndexChanged.connect(self.updateGeometry)
        self.activated.connect(lambda index: self.model_selected.emit(self.itemData(index) or ""))

    def sizeHint(self):
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        metrics = self.fontMetrics()
        return self.style().sizeFromContents(
            QStyle.ContentsType.CT_ComboBox, option,
            QSize(metrics.horizontalAdvance(self.currentText()), metrics.height()), self)

    def minimumSizeHint(self):
        return self.sizeHint()

    def set_current(self, model: str):
        if not model:
            return
        with QSignalBlocker(self):
            if self.findData(model) < 0:
                self.insertItem(0, model, model)
            self.setCurrentIndex(self.findData(model))
        self.updateGeometry()

    def refresh(self, model: str):
        from src.init.brain import main_models
        with QSignalBlocker(self):
            self.clear()
            for name in main_models() or ():
                self.addItem(name, name)
        self.set_current(model)
        self.view().setMinimumWidth(self.view().sizeHintForColumn(0) + 32)

    def showPopup(self):
        self.refresh(self.currentData())
        super().showPopup()


class PrivacyIndicator(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("privacyIndicator")
        self.setText(tr("status.private"))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed
        )

        self.hide()

    def private_toggle(self, worker):
        worker.session.private = False
        self.hide()


class SessionSelector(QToolButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sessionSelector")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAutoRaise(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.hide()

    def set_sessions(self, index: int, count: int, background_running: bool):
        label = tr("session.label", index=index + 1, count=count)
        self.setText(f"{label} ●" if background_running else label)
        self.setToolTip(tr("session.switch_hint"))
        self.setAccessibleName(label)
        if self.property("running") != background_running:
            self.setProperty("running", background_running)
            self.style().unpolish(self)
            self.style().polish(self)
        self.setVisible(count > 1)


class PermissionSelector(QToolButton):
    mode_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("permissionSelector")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAutoRaise(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.mode = PermissionMode.ASK
        self.options = QFrame(self, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                              | Qt.WindowType.NoDropShadowWindowHint)
        self.options.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        options_layout = QHBoxLayout(self.options)
        options_layout.setContentsMargins(0, 0, 0, 0)
        track = QFrame(self.options)
        track.setObjectName("permissionOptions")
        track_layout = QHBoxLayout(track)
        track_layout.setContentsMargins(3, 3, 3, 3)
        track_layout.setSpacing(2)
        options_layout.addWidget(track)
        self.group = QButtonGroup(self)
        for mode in PermissionMode:
            button = QPushButton(mode.name, track)
            button.setObjectName("permissionOption")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setProperty("mode", mode.value)
            self.group.addButton(button)
            track_layout.addWidget(button)
        self.group.buttonClicked.connect(self._select)
        self.clicked.connect(self.show_options)
        self.set_mode(self.mode)

    def set_mode(self, mode):
        self.mode = PermissionMode(mode)
        for button in self.group.buttons():
            button.setChecked(button.property("mode") == self.mode.value)
        self.refresh_language()

    def refresh_language(self):
        self.setText(f" {tr('ui.permissions')} · {self.mode.name}  ")
        self.setToolTip(tr("ui.permissions_hint"))
        self.setAccessibleName(tr("ui.permissions"))
        self.updateGeometry()

    def show_options(self):
        self.options.adjustSize()
        size = self.options.size()
        self.options.move(self.mapToGlobal(QPoint((self.width() - size.width()) // 2,
                                                  -size.height() - 4)))
        self.options.show()

    def _select(self, button):
        self.options.hide()
        mode = PermissionMode(button.property("mode"))
        if mode is not self.mode:
            self.set_mode(mode)
            self.mode_changed.emit(mode.value)
