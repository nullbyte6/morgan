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
"""Workspace-local discovery and execution of existing desktop actions."""

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QApplication, QFrame, QLabel, QLayout, QPlainTextEdit, QListWidget, QListWidgetItem, QMessageBox,
    QVBoxLayout, QWidget,
)
from shiboken6 import isValid

from src.init.lang import tr


@dataclass(frozen=True)
class Command:
    id: str
    label: str
    callback: Callable[[], None]
    keywords: tuple[str, ...] = ()
    available: Callable[[], bool] = lambda: True


class CommandRegistry:
    def __init__(self, commands):
        self.commands = tuple(commands)
        if len({command.id for command in self.commands}) != len(self.commands):
            raise ValueError("Command IDs must be unique")

    def search(self, query):
        tokens = query.casefold().split()
        if not tokens:
            return []
        return [command for command in self.commands
                if all(token in " ".join((tr(command.label), command.id,
                                           *command.keywords)).casefold()
                       for token in tokens)]


class CommandPalette(QFrame):
    def __init__(self, registry, owner):
        super().__init__(owner)
        self.registry = registry
        self.owner = owner
        self.host = None
        self.previous_focus = None
        self.setObjectName("commandPalette")
        self.setFrameShape(QFrame.NoFrame)
        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QLayout.SetNoConstraint)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self.search_input = QPlainTextEdit(self)
        self.search_input.setObjectName("commandPaletteSearch")
        self.search_input.setFrameShape(QFrame.NoFrame)
        self.results = QListWidget(self)
        self.results.setObjectName("commandPaletteResults")
        self.results.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.results.setTextElideMode(Qt.ElideRight)
        self.empty = QLabel(self)
        self.empty.setObjectName("commandPaletteEmpty")
        self.empty.setAlignment(Qt.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.search_input)
        layout.addWidget(self.results)
        layout.addWidget(self.empty)
        self.search_input.textChanged.connect(self._filter)
        self.results.itemClicked.connect(self._execute)
        self.hide()
        self.refresh_language()

    def open(self, host):
        if self.isVisible() and self.host is host:
            self.search_input.setFocus(Qt.ShortcutFocusReason)
            return
        self.dismiss(restore_focus=False)
        self.previous_focus = host.window().focusWidget() or QApplication.focusWidget()
        self.host = host
        self.setParent(host)
        self.results.setCurrentRow(-1)
        self.search_input.clear()
        self._filter()
        self.show()
        self.raise_()
        QApplication.instance().installEventFilter(self)
        self.search_input.setFocus(Qt.ShortcutFocusReason)

    def dismiss(self, *, restore_focus=True):
        if self.host is None:
            return
        QApplication.instance().removeEventFilter(self)
        focus, self.previous_focus = self.previous_focus, None
        self.host = None
        self.hide()
        if isValid(self.owner):
            self.setParent(self.owner)
        if restore_focus and focus is not None and isValid(focus) and focus.isVisible():
            focus.setFocus(Qt.OtherFocusReason)

    def refresh_language(self):
        self.search_input.setPlaceholderText(tr("palette.search"))
        self.search_input.setAccessibleName(tr("palette.search"))
        self.results.setAccessibleName(tr("palette.commands"))
        self.empty.setText(tr("palette.empty"))
        self._filter()

    def _filter(self, _query=None):
        selected = self.results.currentItem()
        selected_id = selected.data(Qt.UserRole).id if selected else None
        self.results.clear()
        query = self.search_input.toPlainText()
        shell = self._shell_command()
        for command in self.registry.search(query) if shell is None else ():
            item = QListWidgetItem(tr(command.label), self.results)
            item.setData(Qt.UserRole, command)
            item.setToolTip(item.text())
            if not command.available():
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled & ~Qt.ItemIsSelectable)
                item.setToolTip(item.text() + "\n" + tr("palette.unavailable"))
            elif self.results.currentItem() is None or command.id == selected_id:
                self.results.setCurrentItem(item)
        self.results.setVisible(self.results.count() > 0)
        self.empty.setText(tr("palette.shell") if shell is not None else tr("palette.empty"))
        self.empty.setVisible(bool(query.strip()) and self.results.count() == 0)
        self._place()

    def _shell_command(self):
        text = self.search_input.toPlainText()
        if not text.startswith(">"):
            return None
        command = text[1:]
        return command[1:] if command.startswith(" ") else command

    def _move(self, direction):
        row = self.results.currentRow()
        for candidate in range(row + direction, self.results.count() if direction > 0 else -1, direction):
            item = self.results.item(candidate)
            if item.flags() & Qt.ItemIsEnabled:
                self.results.setCurrentItem(item)
                self.results.scrollToItem(item)
                return

    def _execute(self, item=None):
        if self.host is None:
            return
        shell = self._shell_command()
        if shell is not None:
            if not shell.strip():
                return
            self.dismiss(restore_focus=False)
            try:
                self.owner.open_terminal_command(shell)
            except Exception as error:
                message = QMessageBox(self.owner)
                message.setIcon(QMessageBox.Critical)
                message.setWindowTitle(tr("palette.shell_error"))
                message.setText(str(error))
                message.setDetailedText(shell)
                message.exec()
            return
        item = item or self.results.currentItem()
        if item is None:
            return
        command = item.data(Qt.UserRole)
        if not command.available():
            self._filter()
            return
        self.dismiss(restore_focus=False)
        command.callback()

    def _place(self):
        if self.host is None:
            return
        area = self.host.rect().adjusted(12, 12, -12, -12)
        width = max(0, min(560, area.width()))
        self.search_input.setFixedHeight(min(6, self.search_input.document().blockCount())
                                        * self.search_input.fontMetrics().lineSpacing() + 24)
        row_height = max(32, self.results.fontMetrics().height() + 18)
        margins = self.layout().contentsMargins()
        overhead = (margins.top() + margins.bottom() + self.layout().spacing()
                    + self.search_input.height())
        orb = getattr(self.owner, "orb", None)
        if orb is not None and self.host.isAncestorOf(orb):
            orb_top = orb.mapTo(self.host, orb.rect().topLeft()).y()
            if orb_top - 12 >= area.y() + overhead:
                area.setBottom(min(area.bottom(), orb_top - 12))
        self.results.setFixedHeight(max(0, min(row_height * min(8, self.results.count()) + 4,
                                              area.height() - overhead)))
        height = min(max(0, area.height()), self.layout().sizeHint().height())
        self.setGeometry(area.x() + (area.width() - width) // 2,
                         area.y(), width, height)

    def eventFilter(self, watched, event):
        if self.host is None:
            return False
        if watched is self.host:
            if event.type() == QEvent.Resize:
                self._place()
            elif event.type() in (QEvent.Hide, QEvent.DeferredDelete):
                self.dismiss(restore_focus=False)
                return False
        elif (watched is getattr(self.owner, "orb", None)
              and event.type() in (QEvent.Move, QEvent.Resize)):
            self._place()
        if event.type() == QEvent.WindowDeactivate and watched is self.owner:
            self.dismiss(restore_focus=False)
        elif event.type() == QEvent.MouseButtonPress:
            if not self.rect().contains(self.mapFromGlobal(event.globalPosition().toPoint())):
                self.dismiss(restore_focus=False)
        elif (event.type() in (QEvent.ShortcutOverride, QEvent.KeyPress)
              and isinstance(watched, QWidget)
              and (watched is self or self.isAncestorOf(watched))
              and event.modifiers() == Qt.NoModifier
              and event.key() in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Escape)):
            event.accept()
            if self._shell_command() is not None and event.key() in (Qt.Key_Up, Qt.Key_Down):
                return False
            if event.type() == QEvent.KeyPress:
                if event.isAutoRepeat() and event.key() in (Qt.Key_Return, Qt.Key_Enter):
                    return True
                if event.key() == Qt.Key_Escape:
                    self.dismiss()
                elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
                    self._execute()
                else:
                    self._move(1 if event.key() == Qt.Key_Down else -1)
            return True
        return False
