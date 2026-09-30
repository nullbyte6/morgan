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
"""Modal panels of the terminal interface: actions, files and models."""
import os
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src.init.tui.i18n import t
from src.init.tui.shell import shell_command_text
from src.init.tui.text import elide, pad
from src.init.tui.widgets import clicked, style


@dataclass(frozen=True)
class Command:
    id: str
    label: Callable[[], str]
    callback: Callable[[], None]
    keywords: tuple[str, ...] = ()
    available: Callable[[], bool] = lambda: True


def scroll_window(count: int, index: int, rows: int) -> int:
    """First visible row keeping the selected row inside a window of rows."""
    if count <= rows:
        return 0
    return min(max(0, index - rows // 2), count - rows)


class Overlay:
    wide = 72

    def title(self) -> str:
        return ""

    def hint(self) -> str:
        return ""

    def lines(self, app, width: int, rows: int) -> list:
        return []

    def on_key(self, app, key: str) -> None:
        pass

    def on_text(self, app, text: str) -> None:
        pass


class PaletteOverlay(Overlay):
    """Search the available actions; text after > runs as a shell command."""

    def __init__(self, commands):
        self.commands = commands
        self.query = ""
        self.index = 0

    def title(self):
        return t("palette.commands")

    def shell(self):
        return shell_command_text(self.query)

    def results(self):
        if self.shell() is not None:
            return []
        tokens = self.query.casefold().split()
        found = []
        for command in self.commands:
            haystack = " ".join((command.label(), command.id, *command.keywords)).casefold()
            if all(token in haystack for token in tokens):
                found.append(command)
        return ([command for command in found if command.available()]
                + [command for command in found if not command.available()])

    def hint(self):
        return t("tui.palette_shell") if self.shell() is not None else t("tui.palette_hint")

    def lines(self, app, width, rows):
        P = app.palette
        lines = []
        query = self.query or ""
        cursor = style(P["accent"], bold=True)
        if query:
            lines.append([(style(P["text"]), " " + elide(query, width - 3)), (cursor, "▏")])
        else:
            lines.append([(style(P["text_subtle"]), " " + t("palette.search"))])
        lines.append([(style(P["border"]), "─" * width)])
        results = self.results()
        if self.shell() is not None:
            lines.append([(style(P["text_muted"]), " " + t("palette.shell"))])
            return lines
        if not results:
            lines.append([(style(P["text_muted"]), " " + t("palette.empty"))])
            return lines
        self.index = min(self.index, len(results) - 1)
        room = max(1, rows - len(lines))
        first = scroll_window(len(results), self.index, room)
        for position, command in enumerate(results[first:first + room], first):
            enabled = command.available()
            selected = position == self.index
            label = command.label() + ("" if enabled else " · " + t("palette.unavailable"))
            if selected and enabled:
                row_style = style(P["on_accent"], P["accent"], bold=True)
            elif enabled:
                row_style = style(P["text"])
            else:
                row_style = style(P["text_disabled"])
            text = " " + elide(label, width - 2)
            lines.append([(row_style, pad(text, width) if selected and enabled else text,
                           clicked(lambda position=position: self.activate(app, position)))])
        return lines

    def activate(self, app, position=None):
        if self.shell() is not None:
            command = self.shell()
            if command.strip():
                app.close_overlay()
                app.session.run_shell(command)
            return
        results = self.results()
        position = self.index if position is None else position
        if not 0 <= position < len(results):
            return
        command = results[position]
        if not command.available():
            return
        app.close_overlay()
        command.callback()

    def move(self, step):
        results = self.results()
        enabled = [position for position, command in enumerate(results) if command.available()]
        if not enabled:
            return
        later = [position for position in enabled if (position - self.index) * step > 0]
        if later:
            self.index = min(later) if step > 0 else max(later)
        else:
            self.index = enabled[0] if step > 0 else enabled[-1]

    def on_key(self, app, key):
        if key == "up":
            self.move(-1)
        elif key == "down":
            self.move(1)
        elif key == "enter":
            self.activate(app)
        elif key == "backspace":
            self.query = self.query[:-1]
            self.index = 0
        elif key == "clear":
            self.query = ""
            self.index = 0

    def on_text(self, app, text):
        self.query += text.replace("\r", "").replace("\n", " ")
        self.index = 0


class ModelOverlay(Overlay):
    wide = 56

    def __init__(self):
        self.index = 0

    def title(self):
        return t("ui.model")

    def hint(self):
        return t("ui.model_hint")

    def lines(self, app, width, rows):
        P = app.palette
        models = app.session.models
        if not models:
            return [[(style(P["text_muted"]), " " + t("palette.empty"))]]
        self.index = min(self.index, len(models) - 1)
        first = scroll_window(len(models), self.index, rows)
        lines = []
        for position, model in enumerate(models[first:first + rows], first):
            current = model == app.session.model
            selected = position == self.index
            mark = "● " if current else "  "
            text = " " + elide(mark + model, width - 2)
            row_style = (style(P["on_accent"], P["accent"], bold=True) if selected
                         else style(P["accent"] if current else P["text"]))
            lines.append([(row_style, pad(text, width) if selected else text,
                           clicked(lambda model=model: self.choose(app, model)))])
        return lines

    def choose(self, app, model):
        app.close_overlay()
        app.session.request_model(model)

    def on_key(self, app, key):
        models = app.session.models
        if key == "up" and models:
            self.index = (self.index - 1) % len(models)
        elif key == "down" and models:
            self.index = (self.index + 1) % len(models)
        elif key == "enter" and models:
            self.choose(app, models[self.index])


class FileOverlay(Overlay):
    """Choose files to attach: Enter opens folders, Space marks, Tab attaches."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.entries = []
        self.selected = {}
        self.index = 0
        self.load()

    def title(self):
        return t("ui.attach_files")

    def hint(self):
        return t("tui.files_hint")

    def load(self):
        entries = []
        if self.directory.parent != self.directory:
            entries.append(("..", self.directory.parent, True))
        elif os.name == "nt":
            entries.append(("..", None, True))
        try:
            with os.scandir(self.directory) as scanner:
                listing = sorted(((entry.name, Path(entry.path), entry.is_dir())
                                  for entry in scanner),
                                 key=lambda item: (not item[2], item[0].casefold()))
            entries.extend(listing)
        except OSError:
            pass
        self.entries = entries
        self.index = 0

    def drives(self):
        self.directory = None
        self.entries = [(f"{letter}:\\", Path(f"{letter}:\\"), True)
                        for letter in string.ascii_uppercase if os.path.exists(f"{letter}:\\")]
        self.index = 0

    def open(self, path):
        if path is None:
            self.drives()
            return
        self.directory = path
        self.load()

    def lines(self, app, width, rows):
        P = app.palette
        header = str(self.directory) if self.directory is not None else ""
        lines = [[(style(P["text_muted"]), " " + elide(header, width - 2, middle=True))],
                 [(style(P["border"]), "─" * width)]]
        room = max(1, rows - len(lines))
        if not self.entries:
            lines.append([(style(P["text_muted"]), " " + t("palette.empty"))])
            return lines
        self.index = min(self.index, len(self.entries) - 1)
        first = scroll_window(len(self.entries), self.index, room)
        for position, (name, path, is_dir) in enumerate(self.entries[first:first + room], first):
            marked = path is not None and str(path) in self.selected
            selected = position == self.index
            box = "[x] " if marked else ("    " if is_dir else "[ ] ")
            label = name + ("/" if is_dir and name != ".." else "")
            text = " " + elide(box + label, width - 2)
            if selected:
                row_style = style(P["on_accent"], P["accent"], bold=True)
            elif marked:
                row_style = style(P["success"], bold=True)
            else:
                row_style = style(P["accent"] if is_dir else P["text"])
            lines.append([(row_style, pad(text, width) if selected else text,
                           clicked(lambda position=position: self.click(app, position)))])
        return lines

    def click(self, app, position):
        if position == self.index:
            self.activate(app)
        else:
            self.index = position

    def toggle(self):
        name, path, is_dir = self.entries[self.index]
        if is_dir or path is None:
            return
        key = str(path)
        if key in self.selected:
            del self.selected[key]
        else:
            self.selected[key] = path

    def confirm(self, app):
        paths = [str(path) for path in self.selected.values()]
        app.close_overlay()
        if paths:
            app.session.add_files(paths)

    def activate(self, app):
        if not self.entries:
            return
        name, path, is_dir = self.entries[self.index]
        if is_dir:
            self.open(path)
            return
        self.selected.setdefault(str(path), path)
        self.confirm(app)

    def on_key(self, app, key):
        count = len(self.entries)
        if key == "up" and count:
            self.index = (self.index - 1) % count
        elif key == "down" and count:
            self.index = (self.index + 1) % count
        elif key == "pageup":
            self.index = max(0, self.index - 8)
        elif key == "pagedown" and count:
            self.index = min(count - 1, self.index + 8)
        elif key == "home":
            self.index = 0
        elif key == "end" and count:
            self.index = count - 1
        elif key == "enter":
            self.activate(app)
        elif key == "tab":
            self.confirm(app)
        elif key in ("backspace", "left"):
            if self.directory is None:
                return
            self.open(self.directory.parent if self.directory.parent != self.directory else None)

    def on_text(self, app, text):
        if text == " " and self.entries:
            self.toggle()
