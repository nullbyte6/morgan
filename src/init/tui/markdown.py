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
"""Markdown responses rendered to prompt_toolkit fragments through Rich."""
import io
from functools import lru_cache


def _theme(palette):
    from rich.theme import Theme

    accent = palette["accent"]
    return Theme({
        "markdown.code": f"{palette['code_inline_text']} on {palette['code_inline_background']}",
        "markdown.h1": f"bold {accent}",
        "markdown.h2": f"bold {accent}",
        "markdown.h3": f"bold {palette['accent_hover']}",
        "markdown.h4": f"bold {palette['text']}",
        "markdown.h5": f"bold {palette['text_secondary']}",
        "markdown.h6": f"italic {palette['text_secondary']}",
        "markdown.link": f"underline {accent}",
        "markdown.link_url": f"underline {palette['text_subtle']}",
        "markdown.item.bullet": f"bold {accent}",
        "markdown.item.number": f"bold {accent}",
        "markdown.block_quote": f"italic {palette['text_muted']}",
        "markdown.hr": palette["border_strong"],
        "markdown.table.header": f"bold {palette['table_header_text']}",
        "markdown.table.border": palette["table_border"],
    })


def _style(style) -> str:
    if style is None:
        return ""
    parts = []
    if style.color is not None:
        red, green, blue = style.color.get_truecolor()
        parts.append(f"fg:#{red:02x}{green:02x}{blue:02x}")
    if style.bgcolor is not None:
        red, green, blue = style.bgcolor.get_truecolor(foreground=False)
        parts.append(f"bg:#{red:02x}{green:02x}{blue:02x}")
    for name, attribute in (("bold", style.bold), ("italic", style.italic),
                            ("underline", style.underline), ("strike", style.strike)):
        if attribute:
            parts.append(name)
    return " ".join(parts)


@lru_cache(maxsize=4)
def _render(text: str, width: int, theme_key: tuple):
    from rich.console import Console
    from rich.markdown import Markdown

    palette = dict(theme_key)
    console = Console(file=io.StringIO(), width=width, force_terminal=True,
                      color_system="truecolor", theme=_theme(palette))
    options = console.options.update(width=width)
    renderable = Markdown(text, code_theme="monokai", hyperlinks=False)
    lines = console.render_lines(renderable, options, pad=False)
    return tuple(tuple((_style(segment.style), segment.text) for segment in line
                       if segment.text and not segment.control)
                 for line in lines)


def render_markdown(text: str, width: int, palette) -> list[list[tuple[str, str]]]:
    """One list of (style, text) fragments per terminal row."""
    if not text.strip():
        return []
    return [list(line) for line in _render(text, max(10, width),
                                           tuple(sorted(palette.colors.items())))]
