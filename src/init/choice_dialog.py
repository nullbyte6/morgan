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
"""A choice dialog built into its parent view instead of opening a separate window."""
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QFrame, QGridLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from .lang import tr

CARD_WIDTH = 460
NEUTRAL_BUTTON = "themesFolderButton"
DANGER_BUTTON = "removeMemoriesButton"


class ChoiceDialog(QWidget):
    """A scrim over the whole parent view with a small card; Escape or a click outside the card closes it."""
    COLUMNS = 2

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("choiceScrim")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self._previous_focus: QWidget | None = None
        self._buttons: list[QPushButton] = []
        parent.installEventFilter(self)

        self.title_label = QLabel()
        self.title_label.setObjectName("novaDialogTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setWordWrap(True)
        self.message_label = QLabel()
        self.message_label.setObjectName("choiceMessage")
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label.setWordWrap(True)
        self.grid = QGridLayout()
        self.grid.setSpacing(12)

        self.card = QFrame()
        self.card.setObjectName("novaCard")
        self.card.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation)
        card = QVBoxLayout(self.card)
        card.setContentsMargins(28, 24, 28, 24)
        card.setSpacing(16)
        card.addWidget(self.title_label)
        card.addWidget(self.message_label)
        card.addLayout(self.grid)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(self.card, 0, Qt.AlignmentFlag.AlignCenter)
        self.hide()

    def ask(self, title: str, message: str, choices: list[tuple]) -> None:
        """Show (text, button object name, callback or None) choices in a grid; the first one takes focus."""
        for button in self._buttons:
            self.grid.removeWidget(button)
            button.deleteLater()
        self._buttons = []
        for column in range(self.COLUMNS):
            self.grid.setColumnStretch(column, 0)
        self.title_label.setText(title)
        self.message_label.setText(message)
        columns = min(len(choices), self.COLUMNS)
        for column in range(columns):
            self.grid.setColumnStretch(column, 1)
        for index, (text, name, callback) in enumerate(choices):
            button = QPushButton(text)
            button.setObjectName(name)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _checked=False, callback=callback: self._choose(callback))
            self.grid.addWidget(button, index // columns, index % columns)
            self._buttons.append(button)
        if not self.isVisible():
            self._previous_focus = QApplication.focusWidget()
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self._buttons[0].setFocus()

    def confirm(self, title: str, message: str, on_confirm, *, danger: bool = True) -> None:
        self.ask(title, message, [
            (tr("ui.cancel"), NEUTRAL_BUTTON, None),
            (tr("command.yes"), DANGER_BUTTON if danger else NEUTRAL_BUTTON, on_confirm)])

    def notify(self, title: str, message: str) -> None:
        self.ask(title, message, [(tr("ui.ok"), NEUTRAL_BUTTON, None)])

    def _choose(self, callback) -> None:
        self.dismiss()
        if callback is not None:
            callback()

    def dismiss(self) -> None:
        self.hide()
        if self._previous_focus is not None:
            try:
                self._previous_focus.setFocus()
            except RuntimeError:
                pass
        self._previous_focus = None

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize and self.isVisible():
            self.setGeometry(self.parentWidget().rect())
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.card.setFixedWidth(max(260, min(CARD_WIDTH, self.width() - 32)))

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self.dismiss()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        self.dismiss()

    def focusNextPrevChild(self, forward: bool) -> bool:
        if not self._buttons:
            return super().focusNextPrevChild(forward)
        current = QApplication.focusWidget()
        index = self._buttons.index(current) if current in self._buttons else -1
        target = self._buttons[(index + (1 if forward else -1)) % len(self._buttons)]
        target.setFocus(Qt.FocusReason.TabFocusReason if forward else Qt.FocusReason.BacktabFocusReason)
        return True
