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
"""Streaming terminal formatting, separate from the original Markdown."""

import re

from pygments.lexers import get_lexer_by_name
from pygments.lexers.special import TextLexer
from pygments.token import Keyword, Name, Number, Operator, Punctuation
from pygments.util import ClassNotFound


KEYWORD_COLOR = "\x1b[35m"
NUMBER_COLOR = "\x1b[38;2;255;165;0m"
SYMBOL_COLOR = "\x1b[36m"
CODE_COLOR = "\x1b[37m"
PROSE_COLOR = "\x1b[90m"
EMPHASIS_COLOR = "\x1b[94m"
INLINE_FORMAT = re.compile(
    r"(?P<code>(?P<ticks>`+).*?(?P=ticks)(?!`))"
    r"|(?<![\\*])\*\*(?=\S)(?P<stars>.+?)(?<=\S)(?<!\\)\*\*(?!\*)"
    r"|(?<![\\\w])__(?=\S)(?P<underscores>.+?)(?<=\S)(?<!\\)__(?!\w)"
)
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})([^\r\n]*)[\r\n]*$")
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
JAVA_TYPES = frozenset("""
    Boolean Byte Character Double Float Integer Long Short Void
    Object String StringBuilder StringBuffer Number Class Enum Record
    System Math Exception RuntimeException Throwable
    Iterable Iterator Comparable Comparator Runnable AutoCloseable
    Collection Collections List ArrayList LinkedList Set HashSet TreeSet
    Map HashMap TreeMap Queue Deque Optional Stream Arrays""".split())


def token_color(kind, value, lexer):
    """Separate builtins/types from control keywords, strings and comments."""
    if (kind in Number or kind in Name.Builtin or kind in Keyword.Type
            or (kind in Keyword and value == "instanceof")
            or ("java" in lexer.aliases and kind in Name
                and (kind in Name.Class or value in JAVA_TYPES))):
        return NUMBER_COLOR
    if kind in Keyword or kind in Operator.Word:
        return KEYWORD_COLOR
    if kind in Operator or kind in Punctuation:
        return SYMBOL_COLOR
    return CODE_COLOR


def markdown_text(text):
    """Keep Markdown whitespace and close an interrupted fenced code block."""
    text = ANSI.sub("", str(text)).replace("\r\n", "\n").replace("\r", "\n")
    fence = None
    for line in text.splitlines():
        marker = FENCE.match(line)
        if marker:
            token, info = marker.groups()
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not info.strip():
                fence = None
    if fence is not None:
        text = text.rstrip("\n") + "\n" + fence + "\n"
    return text


def chunks_group(chunks, *, color=False):
    """Render prose bold in blue and optionally highlight fenced source code.
    Retokenize the current code block so multiline strings and comments retain
    their language context even when the model splits tokens between chunks.
    Unknown or unlabeled languages remain plain code.
    """
    pending = ""
    fence = None
    lexer = None
    code = ""

    def clean_line(line):
        nonlocal fence, lexer, code
        marker = FENCE.match(line)
        if marker:
            token, info = marker.groups()
            if fence is None:
                fence, code = token, ""
                language = info.strip().split()
                try:
                    lexer = get_lexer_by_name(language[0]) if language else TextLexer()
                except ClassNotFound:
                    lexer = TextLexer()
                return line
            if token[0] == fence[0] and len(token) >= len(fence) and not info.strip():
                fence = None
                return (PROSE_COLOR if color else "") + line
        if fence is not None:
            if not color:
                return line
            start = len(code)
            code += line
            highlighted = []
            for offset, kind, value in lexer.get_tokens_unprocessed(code):
                if offset + len(value) <= start:
                    continue
                value = value[max(0, start - offset):]
                shade = token_color(kind, value, lexer)
                highlighted.append(shade + value)
            return "".join(highlighted) + PROSE_COLOR
        def emphasis(match):
            if match.group("code") is not None:
                return match.group(0)
            text = match.group("stars") or match.group("underscores")
            return EMPHASIS_COLOR + text + PROSE_COLOR if color else text

        return INLINE_FORMAT.sub(emphasis, line)

    for chunk in chunks:
        pending += chunk
        while "\n" in pending:
            line, pending = pending.split("\n", 1)
            yield clean_line(line + "\n")
    if pending:
        yield clean_line(pending)
