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
from PySide6.QtWidgets import (QApplication, QFrame, QGridLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)

from .lang import tr

CARD_WIDTH = 460
MAX_GRID_HEIGHT = 260
NEUTRAL_BUTTON = "themesFolderButton"
DANGER_BUTTON = "removeMemoriesButton"


class ChoiceRequest:
    """One question waiting for or receiving an answer; its buttons stay available to update the text."""

    def __init__(self, dialog: "ChoiceDialog", title: str, message: str, choices: list[tuple], columns: int,
                 on_cancel):
        self.dialog = dialog
        self.title = title
        self.message = message
        self.choices = choices
        self.columns = columns
        self.on_cancel = on_cancel
        self.buttons: list[QPushButton] = []
        self.answered = False

    def cancel(self) -> None:
        self.dialog.cancel(self)


class ChoiceDialog(QWidget):
    """A scrim over the whole parent view with a small card; Escape or a click outside the card cancels it."""
    COLUMNS = 2

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("choiceScrim")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self._previous_focus: QWidget | None = None
        self._current: ChoiceRequest | None = None
        self._queue: list[ChoiceRequest] = []
        parent.installEventFilter(self)

        self.title_label = QLabel()
        self.title_label.setObjectName("novaDialogTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setWordWrap(True)
        self.message_label = QLabel()
        self.message_label.setObjectName("choiceMessage")
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label.setWordWrap(True)
        self.grid_box = QWidget()
        self.grid_box.setObjectName("choiceGrid")
        self.grid = QGridLayout(self.grid_box)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(12)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("choiceScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.grid_box)

        self.card = QFrame()
        self.card.setObjectName("novaCard")
        self.card.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation)
        card = QVBoxLayout(self.card)
        card.setContentsMargins(28, 24, 28, 24)
        card.setSpacing(16)
        card.addWidget(self.title_label)
        card.addWidget(self.message_label)
        card.addWidget(self.scroll)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(self.card, 0, Qt.AlignmentFlag.AlignCenter)
        self.hide()

    @classmethod
    def of(cls, widget: QWidget) -> "ChoiceDialog":
        """The dialog covering the given view, created on first use."""
        existing = widget.findChild(cls, options=Qt.FindChildOption.FindDirectChildrenOnly)
        return existing if existing is not None else cls(widget)

    def ask(self, title: str, message: str, choices: list[tuple], *, columns: int | None = None,
            on_cancel=None) -> ChoiceRequest:
        """Queue (text, button object name, callback or None) choices shown in a grid; the first takes focus.

        Escape, a click outside the card or cancel() answers with on_cancel instead of a button."""
        request = ChoiceRequest(self, title, message, choices, min(columns or self.COLUMNS, len(choices)), on_cancel)
        if self._current is None:
            self._previous_focus = QApplication.focusWidget()
            self._present(request)
        else:
            self._queue.append(request)
        return request

    def confirm(self, title: str, message: str, on_confirm, *, danger: bool = True) -> ChoiceRequest:
        return self.ask(title, message, [
            (tr("ui.cancel"), NEUTRAL_BUTTON, None),
            (tr("command.yes"), DANGER_BUTTON if danger else NEUTRAL_BUTTON, on_confirm)])

    def notify(self, title: str, message: str) -> ChoiceRequest:
        return self.ask(title, message, [(tr("ui.ok"), NEUTRAL_BUTTON, None)])

    def cancel(self, request: ChoiceRequest | None = None) -> None:
        """Answer the given request, or the one on screen, as cancelled."""
        request = request or self._current
        if request is None or request.answered:
            return
        if request is self._current:
            self._answer(request.on_cancel)
        elif request in self._queue:
            self._queue.remove(request)
            request.answered = True
            if request.on_cancel is not None:
                request.on_cancel()

    def _present(self, request: ChoiceRequest) -> None:
        self._current = request
        for button in self.grid_box.findChildren(QPushButton):
            self.grid.removeWidget(button)
            button.deleteLater()
        for column in range(self.COLUMNS + 1):
            self.grid.setColumnStretch(column, 0)
        self.title_label.setText(request.title)
        self.message_label.setText(request.message)
        for column in range(request.columns):
            self.grid.setColumnStretch(column, 1)
        for index, (text, name, callback) in enumerate(request.choices):
            button = QPushButton(text)
            button.setObjectName(name)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _checked=False, callback=callback: self._answer(callback))
            self.grid.addWidget(button, index // request.columns, index % request.columns)
            button.ensurePolished()
            request.buttons.append(button)
        self.grid_box.ensurePolished()
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setFixedHeight(min(self.grid_box.sizeHint().height(), MAX_GRID_HEIGHT))
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        request.buttons[0].setFocus()

    def _answer(self, callback) -> None:
        request, self._current = self._current, None
        if request is not None:
            request.answered = True
        if self._queue:
            self._present(self._queue.pop(0))
        else:
            self.hide()
            if self._previous_focus is not None:
                try:
                    self._previous_focus.setFocus()
                except RuntimeError:
                    pass
            self._previous_focus = None
        if callback is not None:
            callback()

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize and self.isVisible():
            self.setGeometry(self.parentWidget().rect())
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.card.setFixedWidth(max(260, min(CARD_WIDTH, self.width() - 32)))

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self.cancel()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        self.cancel()

    def focusNextPrevChild(self, forward: bool) -> bool:
        buttons = self._current.buttons if self._current is not None else []
        if not buttons:
            return super().focusNextPrevChild(forward)
        current = QApplication.focusWidget()
        index = buttons.index(current) if current in buttons else -1
        target = buttons[(index + (1 if forward else -1)) % len(buttons)]
        target.setFocus(Qt.FocusReason.TabFocusReason if forward else Qt.FocusReason.BacktabFocusReason)
        return True
