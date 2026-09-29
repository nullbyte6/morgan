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

from __future__ import annotations

import builtins
import keyword
import re
from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from threading import Event

from pygments.lexer import RegexLexer
from pygments.lexers import get_lexer_by_name, get_lexer_for_filename
from pygments.style import Style
from pygments.token import Comment, Generic, Keyword, Name, Number, Operator, String, Text
from pygments.util import ClassNotFound

from PySide6.QtCore import QRegularExpression, QTimer
from PySide6.QtGui import (
    QFont,
    QSyntaxHighlighter,
    QTextCharFormat,
)

from ..theme import Theme, current_theme, on_theme_changed

_LEXER_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="arlo-lexer")

TOKEN_ROLES = (
    (Comment, "syntax_comment"), (Keyword, "syntax_keyword"),
    (Name.Function, "syntax_function"), (Name.Class, "syntax_class"),
    (Name.Builtin, "syntax_builtin"), (Name.Decorator, "syntax_decorator"),
    (Name.Tag, "syntax_keyword"), (Name.Attribute, "syntax_function"),
    (String, "syntax_string"), (Number, "syntax_number"),
    (Operator, "syntax_decorator"), (Generic.Heading, "syntax_class"),
    (Generic.Subheading, "syntax_class"), (Generic.Inserted, "syntax_string"),
    (Generic.Deleted, "syntax_decorator"),
)


def _rehighlight_preserving_state(highlighter) -> None:
    document = highlighter.document()
    if document is None:
        return
    applying = getattr(highlighter, "_applying", False)
    highlighter._applying = True
    try:
        modified = document.isModified()
        highlighter.rehighlight()
        document.setModified(modified)
    finally:
        highlighter._applying = applying


@lru_cache(maxsize=16)
def pygments_style(theme: Theme) -> type[Style]:
    """Build a Pygments style whose token colors come from the theme."""
    styles = {}
    for token, role in TOKEN_ROLES:
        styles[token] = ("bold " if token in Keyword or token in Generic.Heading else "") + theme.hex(role)
    styles[Generic.Strong] = "bold"
    styles[Generic.Emph] = "italic"
    return type("ArloThemeStyle", (Style,), {
        "background_color": theme.hex("code_block_background"),
        "styles": styles,
    })

class _IgnoreLexer(RegexLexer):
    """Pygments has no built-in lexer for Git/Docker ignore patterns."""
    name = "Ignore patterns"
    tokens = {"root": [
        (r"^#.*$", Comment.Single),
        (r"^!", Operator),
        (r"\\.", String.Escape),
        (r"\*\*?|\?|\[[^\]\n]*\]", String.Regex),
        (r"[^\\*?\[\n]+|.", Text),
        (r"\n", Text),
    ]}


def lexer_for_path(path):
    """Select solely by filename, preserving compound Pygments patterns."""
    name = Path(path).name
    lower = name.lower()
    if lower in {".gitignore", ".dockerignore", ".ignore", ".npmignore"}:
        return _IgnoreLexer()
    aliases = {
        ".editorconfig": "ini", ".gitconfig": "ini",
        ".npmrc": "ini", ".yarnrc": "ini", ".env": "bash",
    }

    alias = aliases.get(lower)
    if lower.endswith(".jsonc"):
        alias = "json"
    elif lower.endswith(".d.ts"):
        alias = "typescript"
    elif lower.endswith(".blade.php"):
        alias = "html+php"
    elif lower.startswith("dockerfile."):
        alias = "docker"
    elif lower.startswith(".env."):
        alias = "bash"
    try:
        if alias:
            return get_lexer_by_name(alias)
        try:
            return get_lexer_for_filename(name)
        except ClassNotFound:
            return get_lexer_for_filename(lower)
    except ClassNotFound:
        return None


def _tokenize_blocks(lexer, text, cancelled):
    """Lex one complete snapshot, then split ranges at Qt block boundaries.

    Using the unprocessed API keeps tabs, whitespace and offsets intact. Full
    context is required for arbitrary Pygments lexers (including delegating
    template lexers); line-by-line RegexLexer stacks are not sufficient.
    """
    lines = text.split("\n")
    starts = []
    offset = 0
    for line in lines:
        starts.append(offset)
        offset += len(line) + 1
    spans = [[] for _ in lines]
    utf16 = {}
    for index, line in enumerate(lines):
        if not line.isascii() and any(ord(char) > 0xffff for char in line):
            positions = [0]
            for char in line:
                positions.append(positions[-1] + (2 if ord(char) > 0xffff else 1))
            utf16[index] = positions
    for start, token, value in lexer.get_tokens_unprocessed(text):
        if cancelled.is_set():
            return None
        end = start + len(value)
        block = max(0, bisect_right(starts, start) - 1)
        while block < len(lines) and starts[block] < end:
            left = max(0, start - starts[block])
            right = min(len(lines[block]), end - starts[block])
            if right > left:
                mapping = utf16.get(block)
                a, b = (mapping[left], mapping[right]) if mapping else (left, right)
                spans[block].append((a, b - a, token))
            block += 1
    return lines, spans


class PygmentsHighlighter(QSyntaxHighlighter):
    """Debounced full-context lexing with cached, constant-time block lookup.

    Edits invalidate pending results immediately. After 180 ms of idle time a
    worker lexes a snapshot; the GUI installs only the latest result. No lexing
    happens in highlightBlock. Retokenizing after a pause is intentional: the
    public Pygments API has no universal resumable lexer state.
    """
    def __init__(self, document, lexer):
        super().__init__(None)
        self.lexer = lexer
        self._formats = {}
        self._cache = None
        self._generation = 0
        self._future = None
        self._cancelled = Event()
        self._applying = False
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(180)
        self._debounce.timeout.connect(self._submit)
        self._poll = QTimer(self)
        self._poll.setInterval(25)
        self._poll.timeout.connect(self._collect)
        self.destroyed.connect(self._cancelled.set)
        self.setParent(document)
        self.setDocument(document)
        on_theme_changed(self.apply_theme)

    def apply_theme(self, theme):
        self._formats.clear()
        _rehighlight_preserving_state(self)

    def setDocument(self, document):
        old = self.document()
        if old is not None:
            old.contentsChange.disconnect(self._changed)
        self._debounce.stop()
        self._poll.stop()
        self._cancelled.set()
        if self._future is not None:
            self._future.cancel()
        self._generation += 1
        self._cache = None
        super().setDocument(document)
        if document is not None:
            document.contentsChange.connect(self._changed)
            self._debounce.start(0)

    def _changed(self, position, removed, added):
        if self._applying or not (removed or added):
            return
        self._generation += 1
        self._cache = None
        self._cancelled.set()
        self._debounce.start(180)

    def _submit(self):
        document = self.document()
        if document is None:
            return
        if self._future is not None and not self._future.done():
            self._debounce.start(180)
            return
        self._cancelled.clear()
        self._submitted_generation = self._generation
        self._future = _LEXER_POOL.submit(
            _tokenize_blocks, self.lexer, document.toPlainText(), self._cancelled)
        self._poll.start()

    def _collect(self):
        if self._future is None or not self._future.done():
            return
        self._poll.stop()
        future, self._future = self._future, None
        if self._submitted_generation != self._generation or self.document() is None:
            return
        try:
            self._cache = future.result()
        except Exception:
            self._cache = None
        self._applying = True
        try:
            modified = self.document().isModified()
            self.rehighlight()
            self.document().setModified(modified)
        finally:
            self._applying = False

    def _format_token(self, token):
        if token in self._formats:
            return self._formats[token]
        fmt = QTextCharFormat()
        for parent, role in TOKEN_ROLES:
            if token in parent:
                fmt.setForeground(current_theme().color(role))
                break
        if token in Keyword or token in Generic.Strong or token in Generic.Heading:
            fmt.setFontWeight(QFont.Bold)
        if token in Generic.Emph:
            fmt.setFontItalic(True)
        self._formats[token] = fmt
        return fmt

    def highlightBlock(self, text):
        if self._cache is None:
            return
        lines, spans = self._cache
        index = self.currentBlock().blockNumber()
        if index < len(lines) and lines[index] == text:
            for start, length, token in spans[index]:
                self.setFormat(start, length, self._format_token(token))


class PythonHighlighter(QSyntaxHighlighter):
    """Python syntax highlighting for Arlo."""

    def __init__(self, document):
        super().__init__(document)
        self.rules = []
        on_theme_changed(self.apply_theme)
        self._add_rule(
            r"\b(?:" + "|".join(
                re.escape(word) for word in keyword.kwlist
            ) + r")\b",
            "keyword",
            bold=True)

        self._add_rule(
            r"\b(?:" + "|".join(
                re.escape(word)
                for word in dir(builtins)
                if not word.startswith("_")
            ) + r")\b",
            "builtin")

        self._add_rule(
            r"\bdef\s+([A-Za-z_]\w*)",
            "function",
            group=1)

        self._add_rule(
            r"\bclass\s+([A-Za-z_]\w*)",
            "class",
            group=1)

        self._add_rule(
            r"@[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*",
            "decorator")

        self._add_rule(
            r"\b(?:0[xX][0-9a-fA-F_]+|"
            r"0[bB][01_]+|"
            r"0[oO][0-7_]+|"
            r"\d[\d_]*(?:\.\d[\d_]*)?"
            r"(?:[eE][+-]?\d+)?)\b",
            "number")

        self._add_rule(
            r"#[^\n]*",
            "comment")

        self.string_format = self._format("string")

        self.single_string = QRegularExpression(
            r"""(?:[rRuUbBfF]{0,2})"""
            r"""(?:'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")""")

        self.triple_string = QRegularExpression(
            r"""(?:[rRuUbBfF]{0,2})('''|\"\"\")""")

    def _format(self, color, bold=False):
        fmt = QTextCharFormat()
        fmt.setForeground(current_theme().color("syntax_" + color))

        if bold:
            fmt.setFontWeight(QFont.Bold)

        return fmt

    def _add_rule(
        self,
        pattern,
        color,
        bold=False,
        group=0):
        self.rules.append((
            QRegularExpression(pattern),
            self._format(color, bold),
            group,
            color,
            bold,
        ))

    def apply_theme(self, theme):
        self.rules = [(regex, self._format(color, bold), group, color, bold)
                      for regex, _, group, color, bold in self.rules]
        self.string_format = self._format("string")
        _rehighlight_preserving_state(self)

    def highlightBlock(self, text: str):
        self.setCurrentBlockState(0)

        for regex, fmt, group, _, _ in self.rules:
            iterator = regex.globalMatch(text)

            while iterator.hasNext():
                match = iterator.next()

                start = match.capturedStart(group)
                length = match.capturedLength(group)

                if start >= 0 and length > 0:
                    self.setFormat(start, length, fmt)

        iterator = self.single_string.globalMatch(text)

        while iterator.hasNext():
            match = iterator.next()

            self.setFormat(
                match.capturedStart(),
                match.capturedLength(),
                self.string_format,
            )

        previous_state = self.previousBlockState()

        if previous_state in (1, 2):
            delimiter = (
                "'''" if previous_state == 1 else '"""')
            start = 0
        else:
            delimiter = None
            start = -1

        while True:
            if delimiter is None:
                match = self.triple_string.match(
                    text,
                    start + 1)

                if not match.hasMatch():
                    break

                delimiter = match.captured(1)
                start = match.capturedStart()
                content_start = match.capturedEnd()

            else:
                content_start = start

            end = text.find(delimiter, content_start)

            if end == -1:
                self.setFormat(
                    start,
                    len(text) - start,
                    self.string_format)

                self.setCurrentBlockState(
                    1 if delimiter == "'''" else 2)
                break

            self.setFormat(
                start,
                end + len(delimiter) - start,
                self.string_format)

            start = end + len(delimiter) - 1
            delimiter = None
