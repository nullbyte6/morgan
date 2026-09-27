"""Workspace-local discovery and execution of existing desktop actions."""

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QApplication, QFrame, QLabel, QLayout, QLineEdit, QListWidget, QListWidgetItem,
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
        self.search_input = QLineEdit(self)
        self.search_input.setObjectName("commandPaletteSearch")
        self.results = QListWidget(self)
        self.results.setObjectName("commandPaletteResults")
        self.results.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.results.setTextElideMode(Qt.ElideRight)
        self.empty = QLabel(self)
        self.empty.setObjectName("commandPaletteEmpty")
        self.empty.setAlignment(Qt.AlignCenter)
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
        for command in self.registry.search(self.search_input.text()):
            item = QListWidgetItem(tr(command.label), self.results)
            item.setData(Qt.UserRole, command)
            item.setToolTip(item.text())
            if not command.available():
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled & ~Qt.ItemIsSelectable)
                item.setToolTip(item.text() + "\n" + tr("palette.unavailable"))
            elif self.results.currentItem() is None or command.id == selected_id:
                self.results.setCurrentItem(item)
        self.results.setVisible(self.results.count() > 0)
        self.empty.setVisible(bool(self.search_input.text().strip()) and self.results.count() == 0)
        self._place()

    def _move(self, direction):
        row = self.results.currentRow()
        for candidate in range(row + direction, self.results.count() if direction > 0 else -1, direction):
            item = self.results.item(candidate)
            if item.flags() & Qt.ItemIsEnabled:
                self.results.setCurrentItem(item)
                self.results.scrollToItem(item)
                return

    def _execute(self, item=None):
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
        row_height = max(32, self.results.fontMetrics().height() + 18)
        margins = self.layout().contentsMargins()
        overhead = (margins.top() + margins.bottom() + self.layout().spacing()
                    + self.search_input.sizeHint().height())
        self.results.setFixedHeight(max(0, min(row_height * min(8, self.results.count()) + 4,
                                              area.height() - overhead)))
        height = min(max(0, area.height()), self.layout().sizeHint().height())
        self.setGeometry(area.x() + (area.width() - width) // 2,
                         area.y() + max(0, (area.height() - height) // 3), width, height)

    def eventFilter(self, watched, event):
        if self.host is None:
            return False
        if watched is self.host:
            if event.type() == QEvent.Resize:
                self._place()
            elif event.type() in (QEvent.Hide, QEvent.DeferredDelete):
                self.dismiss(restore_focus=False)
                return False
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
            if event.type() == QEvent.KeyPress:
                if event.key() == Qt.Key_Escape:
                    self.dismiss()
                elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
                    self._execute()
                else:
                    self._move(1 if event.key() == Qt.Key_Down else -1)
            return True
        return False
