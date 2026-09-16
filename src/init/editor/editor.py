from __future__ import annotations

import os
from pathlib import Path

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.processors import (
    HighlightSearchProcessor,
    HighlightSelectionProcessor)

from prompt_toolkit.lexers import PygmentsLexer
from pygments.lexers import TextLexer, get_lexer_for_filename
from pygments.util import ClassNotFound

from .keybindings import create_keybindings
from .styles import EDITOR_STYLE


class NoraEditor:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()

        if not self.path.exists():
            raise FileNotFoundError(f"File not found: {self.path}")

        if not self.path.is_file():
            raise IsADirectoryError(f"Not a file: {self.path}")

        self.original_text = self._read_file()
        self.message = ""
        self.quit_pending = False

        self.buffer = Buffer(
            document=Document(
                text=self.original_text,
                cursor_position=0),
            multiline=True,
            on_text_changed=self._on_text_changed,
        )

        self.application = self._create_application()

    @property
    def modified(self) -> bool:
        return self.buffer.text != self.original_text

    def _read_file(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return self.path.read_text(
                encoding="utf-8",
                errors="replace")

    def _on_text_changed(self, _) -> None:
        self.quit_pending = False

    def set_message(self, message: str) -> None:
        self.message = message

        if hasattr(self, "application"):
            self.application.invalidate()

    def save(self) -> None:
        temporary = self.path.with_name(
            f".{self.path.name}.nora.tmp")

        try:
            temporary.write_text(
                self.buffer.text,
                encoding="utf-8",
            )

            os.replace(temporary, self.path)

            self.original_text = self.buffer.text
            self.quit_pending = False

            self.set_message(f"Saved: {self.path.name}")

        except Exception as error:
            try:
                if temporary.exists():
                    temporary.unlink()
            except OSError:
                pass

            self.set_message(f"Save error: {error}")

    def _get_lexer(self):
        try:
            lexer = get_lexer_for_filename(str(self.path))
            return PygmentsLexer(lexer.__class__)
        except ClassNotFound:
            return PygmentsLexer(TextLexer)

    def _status_bar(self):
        document = self.buffer.document

        modified = " [+]" if self.modified else ""

        return [
            ("class:status.filename", f" {self.path.name}"),
            ("class:status.modified", modified),
            (
                "class:status",
                f"  Ln {document.cursor_position_row + 1}, "
                f"Col {document.cursor_position_col + 1}"
                "   Ctrl+S Save   Ctrl+Q Exit "),
        ]

    def _message_bar(self):
        if not self.message:
            return ""

        return f" {self.message} "

    def _create_application(self) -> Application:
        editor_window = Window(
            content=BufferControl(
                buffer=self.buffer,
                lexer=self._get_lexer(),
                input_processors=[
                    HighlightSearchProcessor(),
                    HighlightSelectionProcessor(),
                ]),
            wrap_lines=False,
            left_margins=[])

        status_window = Window(
            content=FormattedTextControl(
                self._status_bar),
            height=1,
            style="class:status")

        message_window = Window(
            content=FormattedTextControl(
                self._message_bar),
            height=1,
            style="class:message")

        root = HSplit([
            editor_window,
            status_window,
            message_window,
        ])

        return Application(
            layout=Layout(root,
                focused_element=editor_window),
            key_bindings=create_keybindings(self),
            style=EDITOR_STYLE,
            full_screen=True,
            mouse_support=True)

    def run(self) -> None:
        self.application.run()


def open_in_editor(path: str) -> str:
    """
    Open an existing text file in Nora's built-in interactive editor.
    Use this tool when the user explicitly wants to manually edit a file
    themselves inside Nora. Do not use it when Nora has been asked to edit
    the file automatically.
    """
    from src.init.brain import get_working_directory

    requested = Path(path).expanduser()

    if not requested.is_absolute():
        requested = Path(get_working_directory()) / requested

    requested = requested.resolve()

    if not requested.exists():
        return f"File not found: {requested}"

    if not requested.is_file():
        return f"Not a file: {requested}"

    editor = NoraEditor(requested)
    editor.run()

    return f"Editor closed: {requested}"