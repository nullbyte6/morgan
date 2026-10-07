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

"""Every keyboard shortcut of the desktop app, and the overlay listing them while Ctrl is held."""

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, QPropertyAnimation, QTimer, Qt
from PySide6.QtGui import QBrush, QKeySequence, QPainter, QShortcut, QTextLength, QTextTable
from PySide6.QtWidgets import (QApplication, QFrame, QGraphicsOpacityEffect, QLabel,
                               QTextBrowser, QVBoxLayout, QWidget)

from src.init.lang import tr
from src.init.theme import current_theme

HINT_HOLD_MS = 2000
HINT_FADE_MS = 180


@dataclass(frozen=True)
class Hotkey:
    group: str
    sequences: tuple[str, ...]


HOTKEYS = {
    "command_palette": Hotkey("general", ("Ctrl+K",)),
    "record": Hotkey("general", ("Ctrl+R",)),
    "mic_mute": Hotkey("general", ("Ctrl+Shift+M",)),
    "new_session": Hotkey("general", ("Ctrl+Shift+N",)),
    "close_session": Hotkey("general", ("Ctrl+Shift+W",)),
    "zoom_in": Hotkey("general", ("Ctrl++", "Ctrl+=", "Ctrl+Shift+=")),
    "zoom_out": Hotkey("general", ("Ctrl+-",)),
    "zoom_reset": Hotkey("general", ("Ctrl+0",)),
    "open_editor": Hotkey("workspace", ("Ctrl+E",)),
    "open_terminal": Hotkey("workspace", ("Ctrl+T",)),
    "open_settings": Hotkey("workspace", ("Ctrl+Alt+S",)),
    "close_panel": Hotkey("workspace", ("Ctrl+W",)),
    "focus_left": Hotkey("workspace", ("Ctrl+Alt+Left",)),
    "focus_right": Hotkey("workspace", ("Ctrl+Alt+Right",)),
    "focus_up": Hotkey("workspace", ("Ctrl+Alt+Up",)),
    "focus_down": Hotkey("workspace", ("Ctrl+Alt+Down",)),
    "nova_dock": Hotkey("nova", ("Ctrl+B",)),
    "nova_home": Hotkey("nova", ("Ctrl+H",)),
    "nova_notifications": Hotkey("nova", ("Ctrl+Alt+N",)),
    "nova_me": Hotkey("nova", ("Ctrl+M",)),
    "nova_diary": Hotkey("nova", ("Ctrl+L",)),
    "nova_journal": Hotkey("nova", ("Ctrl+J",)),
    "journal_add": Hotkey("nova", ("Ctrl+Return",)),
    "save_or_search": Hotkey("files", ("Ctrl+S",)),
    "open_file": Hotkey("files", ("Ctrl+O",)),
    "find": Hotkey("files", ("Ctrl+F",)),
    "find_close": Hotkey("files", ("Esc",)),
}


def sequences(name: str) -> list[QKeySequence]:
    return [QKeySequence(text) for text in HOTKEYS[name].sequences]


def bind(name: str, parent: QObject, callback,
         context: Qt.ShortcutContext = Qt.ApplicationShortcut) -> list[QShortcut]:
    """Create one shortcut per sequence of a named hotkey, all calling callback."""
    shortcuts = []
    for sequence in sequences(name):
        shortcut = QShortcut(sequence, parent)
        shortcut.setContext(context)
        shortcut.activated.connect(callback)
        shortcuts.append(shortcut)
    return shortcuts


def matches(event, name: str) -> bool:
    return QKeySequence(event.keyCombination()) in sequences(name)


def markdown_table() -> str:
    lines = [f"| {tr('hotkeys.col_group')} | {tr('hotkeys.col_shortcut')} | {tr('hotkeys.col_action')} |",
             "| --- | --- | --- |"]
    previous = None
    for name, hotkey in HOTKEYS.items():
        group = tr(f"hotkeys.group_{hotkey.group}") if hotkey.group != previous else ""
        previous = hotkey.group
        keys = " / ".join(f"`{text}`" for text in hotkey.sequences)
        lines.append(f"| {group} | {keys} | {tr(f'hotkeys.action.{name}')} |")
    return "\n".join(lines)


class HotkeyOverlay(QFrame):
    """A translucent sheet over the window listing every shortcut in a markdown table."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.NoFocus)
        self.card = QFrame(self)
        self.card.setObjectName("HotkeyCard")
        self.title = QLabel(self.card)
        self.hint = QLabel(self.card)
        self.table = QTextBrowser(self.card)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setFrameShape(QFrame.NoFrame)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(24, 14, 24, 14)
        layout.addWidget(self.title)
        layout.addWidget(self.hint)
        layout.addWidget(self.table, 1)
        self.effect = QGraphicsOpacityEffect(self)
        self.effect.setOpacity(0.0)
        self.setGraphicsEffect(self.effect)
        self.fade = QPropertyAnimation(self.effect, b"opacity", self)
        self.fade.setDuration(HINT_FADE_MS)
        self.fade.finished.connect(self._fade_finished)
        self.hide()

    def refresh(self) -> None:
        theme = current_theme()
        self.title.setText(tr("hotkeys.title"))
        self.hint.setText(tr("hotkeys.hint"))
        self.setStyleSheet(theme.render(
            "#HotkeyCard { background: @surface_raised; border: 1px solid @border_strong; "
            "border-radius: 12px; } "
            "QLabel { background: transparent; color: @text; font-size: 18px; font-weight: 600; } "
            "QTextBrowser { background: transparent; color: @text; }"))
        self.hint.setStyleSheet(f"color: {theme.css('text_muted')}; font-size: 12px; font-weight: 400;")
        self.table.document().setDefaultStyleSheet(
            f"code {{ color: {theme.css('accent')}; }} th {{ color: {theme.css('text_secondary')}; }}")
        self.table.setMarkdown(markdown_table())
        for frame in self.table.document().rootFrame().childFrames():
            if isinstance(frame, QTextTable):
                table_format = frame.format()
                table_format.setCellPadding(2)
                table_format.setBorder(1)
                table_format.setBorderBrush(QBrush(theme.color("border")))
                table_format.setWidth(QTextLength(QTextLength.PercentageLength, 100))
                frame.setFormat(table_format)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), current_theme().color("surface_sunken", 215))

    def present(self, window: QWidget) -> None:
        if self.parentWidget() is not window:
            self.setParent(window)
        self.setGeometry(window.rect())
        self.refresh()
        width = min(760, max(320, window.width() - 48))
        self.table.document().setTextWidth(width - 48)
        height = min(int(self.table.document().size().height()) + 100, window.height() - 48)
        self.card.setGeometry((window.width() - width) // 2, max(24, (window.height() - height) // 2),
                              width, height)
        self.show()
        self.raise_()
        self._animate(1.0)

    def dismiss(self) -> None:
        if self.isVisible():
            self._animate(0.0)

    def _animate(self, target: float) -> None:
        self.fade.stop()
        self.fade.setStartValue(self.effect.opacity())
        self.fade.setEndValue(target)
        self.fade.start()

    def _fade_finished(self) -> None:
        if self.effect.opacity() <= 0.0:
            self.hide()


class HotkeyHints(QObject):
    """Opens the shortcut overlay when Ctrl is held on its own, and closes it when released."""

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.overlay: HotkeyOverlay | None = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(HINT_HOLD_MS)
        self.timer.timeout.connect(self._show)

    def install(self) -> None:
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        kind = event.type()
        if kind == QEvent.KeyPress:
            if event.key() == Qt.Key_Control:
                if not event.isAutoRepeat() and not event.modifiers() & ~Qt.ControlModifier:
                    self.timer.start()
            else:
                self._cancel()
        elif kind == QEvent.KeyRelease:
            if event.key() == Qt.Key_Control and not event.isAutoRepeat():
                self._cancel()
        elif kind in (QEvent.WindowDeactivate, QEvent.ApplicationDeactivate):
            self._cancel()
        return False

    def _show(self) -> None:
        window = QApplication.activeWindow()
        if window is None:
            return
        if self.overlay is None:
            self.overlay = HotkeyOverlay(window)
        self.overlay.present(window)

    def _cancel(self) -> None:
        self.timer.stop()
        if self.overlay is not None:
            self.overlay.dismiss()
