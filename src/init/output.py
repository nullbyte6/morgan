"""Streaming terminal formatting, separate from the original Markdown."""

import re

from pygments.lexers import get_lexer_by_name
from pygments.lexers.special import TextLexer
from pygments.token import Keyword, Number, Operator, Punctuation
from pygments.util import ClassNotFound


KEYWORD_COLOR = "\x1b[35m"
NUMBER_COLOR = "\x1b[38;2;255;165;0m"
SYMBOL_COLOR = "\x1b[36m"
CODE_COLOR = "\x1b[37m"
PROSE_COLOR = "\x1b[90m"
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})([^\r\n]*)[\r\n]*$")
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


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
    """Remove prose bold markers and optionally highlight fenced source code.

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
                shade = (KEYWORD_COLOR if kind in Keyword else
                         NUMBER_COLOR if kind in Number else
                         SYMBOL_COLOR if kind in Operator or kind in Punctuation else
                         CODE_COLOR)
                highlighted.append(shade + value)
            return "".join(highlighted) + PROSE_COLOR
        parts = re.split(r"(`+[^`]*`+)", line)
        for index in range(0, len(parts), 2):
            parts[index] = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"\1", parts[index])
        return "".join(parts)

    for chunk in chunks:
        pending += chunk
        while "\n" in pending:
            line, pending = pending.split("\n", 1)
            yield clean_line(line + "\n")
    if pending:
        yield clean_line(pending)
