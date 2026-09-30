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
"""Width-aware text helpers shared by the terminal widgets."""
import re
from functools import lru_cache

from prompt_toolkit.utils import get_cwidth

SUBTITLE_WIDTH = 56
SUBTITLE_LINES = 3
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_FONTS = ("4max", "small", "mini")


def width_of(text: str) -> int:
    return sum(get_cwidth(character) for character in text)


def pad(text: str, width: int) -> str:
    """Pad with spaces to a display width."""
    return text + " " * max(0, width - width_of(text))


def elide(text: str, width: int, *, middle: bool = False) -> str:
    """Shorten text to a display width with an ellipsis."""
    if width <= 0:
        return ""
    if width_of(text) <= width:
        return text
    if width == 1:
        return "…"
    if middle and width >= 5:
        head = (width - 1) // 2
        tail = width - 1 - head
        return take(text, head) + "…" + take(text, tail, from_end=True)
    return take(text, width - 1) + "…"


def take(text: str, width: int, *, from_end: bool = False) -> str:
    result, used = [], 0
    for character in (reversed(text) if from_end else text):
        size = get_cwidth(character)
        if used + size > width:
            break
        used += size
        result.append(character)
    return "".join(reversed(result) if from_end else result)


def wrap(text: str, width: int) -> list[str]:
    """Greedy word wrap of each paragraph by display width."""
    width = max(1, width)
    lines = []
    for paragraph in text.split("\n"):
        line, used = "", 0
        for word in paragraph.split(" "):
            size = width_of(word)
            if line and used + 1 + size <= width:
                line += " " + word
                used += 1 + size
                continue
            if line:
                lines.append(line)
                line, used = "", 0
            while size > width:
                piece = take(word, width) or word[0]
                lines.append(piece)
                word = word[len(piece):]
                size = width_of(word)
            line, used = word, size
        lines.append(line)
    return lines


def subtitle_lines(text: str, available: int) -> list[str]:
    """The last lines of a subtitle, wrapped like the desktop's caption."""
    return wrap(text, min(SUBTITLE_WIDTH, max(1, available)))[-SUBTITLE_LINES:]


def bold_fragments(text: str, style: str, bold_style: str) -> list[tuple[str, str]]:
    """Enbold **spans** without rendering the surrounding Markdown."""
    fragments, position = [], 0
    for match in _BOLD.finditer(text):
        if match.start() > position:
            fragments.append((style, text[position:match.start()]))
        fragments.append((bold_style, match.group(1)))
        position = match.end()
    if position < len(text):
        fragments.append((style, text[position:]))
    return fragments


def elapsed(seconds: float) -> str:
    total = int(seconds)
    minutes, seconds = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


@lru_cache(maxsize=16)
def _figlet(font: str):
    from pyfiglet import Figlet
    return Figlet(font=font, width=400)


@lru_cache(maxsize=32)
def banner(name: str, columns: int, rows: int) -> tuple[str, ...]:
    """The assistant's name as pyfiglet art that fits the terminal, or plain text."""
    if rows >= 18:
        for font in _FONTS:
            try:
                art = _figlet(font).renderText(name).rstrip("\n").split("\n")
            except Exception:
                continue
            art = [line.rstrip() for line in art]
            while art and not art[-1].strip():
                art.pop()
            while art and not art[0].strip():
                art.pop(0)
            if not art:
                continue
            indent = min(len(line) - len(line.lstrip()) for line in art if line.strip())
            art = [line[indent:] for line in art]
            size = max(width_of(line) for line in art)
            if size <= columns - 2:
                return tuple(line.ljust(size) for line in art)
    return (name,)
