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

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import (
    QColor,
    QFont,
    QSyntaxHighlighter,
    QTextCharFormat,
)


class PythonHighlighter(QSyntaxHighlighter):
    """Python syntax highlighting for Arlo."""
    COLORS = {
        "keyword": "#c6a0f6",
        "builtin": "#f5a97f",
        "function": "#8bd5ca",
        "class": "#eed49f",
        "string": "#a6da95",
        "number": "#f5a97f",
        "comment": "#6e738d",
        "decorator": "#f5bde6",
    }

    def __init__(self, document):
        super().__init__(document)
        self.rules = []
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
        fmt.setForeground(QColor(self.COLORS[color]))

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
        ))

    def highlightBlock(self, text: str):
        self.setCurrentBlockState(0)

        for regex, fmt, group in self.rules:
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
