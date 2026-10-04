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
import subprocess
import time
from pathlib import Path

from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtWidgets import *

from src.init.config import PermissionMode
from src.init.lang import tr
from src.init.theme import current_theme, on_theme_changed
from src.platforms import current_platform


def _draw_shield(painter):
    outline = QPainterPath()
    outline.moveTo(12, 3)
    outline.lineTo(4, 6)
    outline.lineTo(4, 12)
    outline.cubicTo(4, 16.5, 7.2, 20, 12, 21)
    outline.cubicTo(16.8, 20, 20, 16.5, 20, 12)
    outline.lineTo(20, 6)
    outline.closeSubpath()
    painter.drawPath(outline)
    painter.drawPolyline([QPointF(9, 12), QPointF(11, 14), QPointF(15, 10)])


def _draw_lock(painter):
    painter.drawRoundedRect(QRectF(4, 11, 16, 10), 2, 2)
    shackle = QPainterPath()
    shackle.moveTo(8, 11)
    shackle.lineTo(8, 7)
    shackle.arcTo(QRectF(8, 3, 8, 8), 180, -180)
    shackle.lineTo(16, 11)
    painter.drawPath(shackle)


def line_icon(draw, normal_role, active_role, size=18) -> QIcon:
    theme = current_theme()
    icon = QIcon()
    ratio = 2
    for mode, role in ((QIcon.Mode.Normal, normal_role), (QIcon.Mode.Active, active_role)):
        pixmap = QPixmap(size * ratio, size * ratio)
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(size / 24, size / 24)
        pen = QPen(theme.color(role), 2.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        draw(painter)
        painter.end()
        icon.addPixmap(pixmap, mode)
    return icon


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
                creationflags=current_platform().no_window_flags,
            )
            if result.returncode == 0:
                branch = result.stdout.strip()
            elif result.returncode == 1:
                result = subprocess.run(
                    ["git", "-C", path, "rev-parse", "--short", "HEAD"],
                    capture_output=True, text=True, errors="replace", timeout=1,
                    creationflags=current_platform().no_window_flags,
                )
                if result.returncode == 0:
                    branch = f"detached:{result.stdout.strip()}"
        except (OSError, subprocess.TimeoutExpired):
            pass
        self.setText(f"  {branch} ")
        self.setToolTip(branch)
        self.setVisible(bool(branch))


class PopupCorners(QObject):
    """Rounds only the corners of a dropdown list that face away from its combo box."""

    def __init__(self, combo):
        super().__init__(combo)
        self.combo = combo
        self.popup = combo.view().window()
        self.popup.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
        self.popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.popup.installEventFilter(self)

    def eventFilter(self, watched, event):
        if watched is self.popup and event.type() in (QEvent.Type.Show, QEvent.Type.Move):
            opens = ("up" if self.popup.geometry().center().y()
                     < self.combo.mapToGlobal(self.combo.rect().center()).y() else "down")
            options = self.combo.view()
            if options.property("opens") != opens:
                options.setProperty("opens", opens)
                options.style().unpolish(options)
                options.style().polish(options)
        return False


class PrivacyIndicator(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("privacyIndicator")
        self.setToolTip(tr("status.private"))
        self.setAccessibleName(tr("status.private"))
        self.setIconSize(QSize(18, 18))
        self.setFixedSize(32, 32)
        self.apply_theme()
        on_theme_changed(self.apply_theme)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed
        )

        self.hide()

    def apply_theme(self, *_):
        self.setIcon(line_icon(_draw_lock, "private_indicator", "private_indicator"))

    def private_toggle(self, worker):
        worker.session.private = False
        self.hide()


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
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.setIconSize(QSize(18, 18))
        self.setFixedSize(32, 32)
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
        self.apply_theme()
        on_theme_changed(self.apply_theme)
        self.set_mode(self.mode)

    def apply_theme(self, *_):
        self.setIcon(line_icon(_draw_shield, "text_muted", "text"))

    def set_mode(self, mode):
        self.mode = PermissionMode(mode)
        for button in self.group.buttons():
            button.setChecked(button.property("mode") == self.mode.value)
        self.refresh_language()

    def refresh_language(self):
        self.setToolTip(f"{tr('ui.permissions')} · {self.mode.name}\n{tr('ui.permissions_hint')}")
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


class IndicatorFade(QObject):
    def __init__(self, row, composer):
        super().__init__(row)
        self._row = row
        composer.installEventFilter(self)
        self._composer = composer
        self._set_resting(True)

    def eventFilter(self, watched, event):
        if watched is self._composer:
            if event.type() == QEvent.Type.Enter:
                self._set_resting(False)
            elif event.type() == QEvent.Type.Leave:
                self._set_resting(True)
        return False

    def _set_resting(self, resting):
        self._row.setProperty("resting", resting)
        for widget in (self._row, *self._row.findChildren(QWidget)):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
