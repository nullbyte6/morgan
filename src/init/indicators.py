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