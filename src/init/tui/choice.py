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
"""The terminal interface's choice dialog: a centered title and message over a grid of buttons."""
from dataclasses import dataclass
from typing import Callable

from src.init.tui.i18n import t
from src.init.tui.text import elide, width_of, wrap
from src.init.tui.widgets import clicked, style

COLUMNS = 2
MAX_WIDTH = 76
MAX_MESSAGE_LINES = 12


@dataclass(frozen=True)
class Choice:
    label: str | Callable[[], str]
    callback: Callable[[], None] | None = None
    tone: str = "accent"
    keys: tuple[str, ...] = ()

    def text(self) -> str:
        return self.label() if callable(self.label) else self.label


class ChoiceRequest:
    """One question waiting for or receiving an answer."""

    def __init__(self, dialog: "ChoiceDialog", title: str, message: str, choices: list[Choice], columns: int,
                 default: int, on_cancel, tone: str):
        self.dialog = dialog
        self.title = title
        self.message = message
        self.choices = choices
        self.columns = columns
        self.index = default
        self.on_cancel = on_cancel
        self.tone = tone
        self.answered = False

    def cancel(self) -> None:
        self.dialog.cancel(self)


class ChoiceDialog:
    """Questions shown one at a time, the others queued; Esc, Ctrl+C or cancel() answer as cancelled."""

    def __init__(self, on_change: Callable[[], None] | None = None):
        self.on_change = on_change
        self.current: ChoiceRequest | None = None
        self.queue: list[ChoiceRequest] = []

    @property
    def visible(self) -> bool:
        return self.current is not None

    def ask(self, title: str, message: str, choices: list[Choice], *, columns: int | None = None, default: int = 0,
            on_cancel=None, tone: str = "accent") -> ChoiceRequest:
        request = ChoiceRequest(self, title, message, choices, min(columns or COLUMNS, len(choices)), default,
                                on_cancel, tone)
        if self.current is None:
            self.current = request
        else:
            self.queue.append(request)
        self._changed()
        return request

    def confirm(self, title: str, message: str, on_confirm, *, tone: str = "accent") -> ChoiceRequest:
        return self.ask(title, message, [
            Choice(t("ui.cancel"), None, "accent", ("c", "C")),
            Choice(t("command.yes"), on_confirm, tone, ("y", "Y", "s", "S"))])

    def notify(self, title: str, message: str) -> ChoiceRequest:
        return self.ask(title, message, [Choice(t("ui.ok"), None, "accent", ("o", "O"))])

    def cancel(self, request: ChoiceRequest | None = None) -> None:
        request = request or self.current
        if request is None or request.answered:
            return
        if request is self.current:
            self._answer(request.on_cancel)
        elif request in self.queue:
            self.queue.remove(request)
            request.answered = True
            if request.on_cancel is not None:
                request.on_cancel()

    def _answer(self, callback) -> None:
        request = self.current
        if request is not None:
            request.answered = True
        self.current = self.queue.pop(0) if self.queue else None
        self._changed()
        if callback is not None:
            callback()

    def _changed(self) -> None:
        if self.on_change is not None:
            self.on_change()

    def choose(self, position: int) -> None:
        request = self.current
        if request is not None and 0 <= position < len(request.choices):
            self._answer(request.choices[position].callback)

    def activate(self) -> None:
        if self.current is not None:
            self.choose(self.current.index)

    def move(self, key: str) -> None:
        request = self.current
        if request is None:
            return
        count, columns = len(request.choices), request.columns
        if key in ("left", "s-tab"):
            request.index = (request.index - 1) % count
        elif key in ("right", "tab"):
            request.index = (request.index + 1) % count
        elif key == "up" and request.index - columns >= 0:
            request.index -= columns
        elif key == "down" and request.index + columns < count:
            request.index += columns
        self._changed()

    def on_text(self, text: str) -> None:
        request = self.current
        if request is None:
            return
        for position, choice in enumerate(request.choices):
            if text in choice.keys:
                self.choose(position)
                return

    def width(self, columns: int) -> int:
        return max(30, min(MAX_WIDTH, columns - 4))

    @staticmethod
    def _centered(text: str, width: int) -> str:
        return " " * max(0, (width - width_of(text)) // 2) + text

    def lines(self, palette, columns: int) -> list[list]:
        """Fragment lines for the open question, sized for a terminal of the given width."""
        request = self.current
        if request is None:
            return []
        inner = self.width(columns) - 2
        tone = palette[request.tone]
        lines = [[(style(tone, bold=True), self._centered(elide(request.title, inner - 2), inner))], []]
        paragraphs = [line for paragraph in request.message.strip().split("\n") for line in wrap(paragraph, inner - 4)]
        for text in paragraphs[-MAX_MESSAGE_LINES:]:
            lines.append([(style(palette["text"]), self._centered(text, inner))])
        lines.append([])
        gap = 2
        cell = max(8, (inner - 4 - gap * (request.columns - 1)) // request.columns)
        for first in range(0, len(request.choices), request.columns):
            row = [("", " " * ((inner - cell * request.columns - gap * (request.columns - 1)) // 2))]
            for position in range(first, min(first + request.columns, len(request.choices))):
                choice = request.choices[position]
                label = elide(choice.text(), cell - 2)
                gap_left = (cell - width_of(label)) // 2
                text = " " * gap_left + label + " " * (cell - width_of(label) - gap_left)
                selected = position == request.index
                button = (style(palette["on_accent"], palette[choice.tone], bold=True) if selected
                          else style(palette["text"], palette["surface"]))
                if position > first:
                    row.append(("", " " * gap))
                row.append((button, text, clicked(lambda position=position: self.choose(position))))
            lines.append(row)
            lines.append([])
        return lines[:-1]

    def fragments(self, palette, columns: int) -> list:
        lines = self.lines(palette, columns)
        fragments = []
        for position, line in enumerate(lines):
            fragments.extend(line)
            if position < len(lines) - 1:
                fragments.append(("", "\n"))
        return fragments

    def height(self, palette, columns: int) -> int:
        return len(self.lines(palette, columns))

    def border(self, palette) -> str:
        return style(palette[self.current.tone if self.current is not None else "accent"])
