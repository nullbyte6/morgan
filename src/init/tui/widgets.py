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
"""Small prompt_toolkit building blocks: scheduling, rounded boxes and scrolling."""
import logging

from prompt_toolkit.layout import Dimension, HSplit, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.mouse_events import MouseButton, MouseEventType

log = logging.getLogger("assistant.tui")


class Scheduler:
    """Marshals callbacks onto the interface's asyncio loop."""

    def __init__(self, loop):
        self.loop = loop

    def _call(self, function, arguments):
        try:
            function(*arguments)
        except Exception:
            log.exception("Interface callback failed")

    def post(self, function, *arguments):
        self.loop.call_soon_threadsafe(self._call, function, arguments)

    def later(self, delay, function, *arguments):
        return self.loop.call_later(delay, self._call, function, arguments)

    def cancel(self, handle):
        if handle is not None:
            handle.cancel()


def style(fg=None, bg=None, *, bold=False, italic=False, dim=False, underline=False) -> str:
    parts = []
    if fg:
        parts.append(f"fg:{fg}")
    if bg:
        parts.append(f"bg:{bg}")
    for name, enabled in (("bold", bold), ("italic", italic), ("dim", dim), ("underline", underline)):
        if enabled:
            parts.append(name)
    return " ".join(parts)


def clicked(action):
    """A fragment mouse handler that runs action on a left-button release."""
    def handler(mouse_event):
        if (mouse_event.event_type == MouseEventType.MOUSE_UP
                and mouse_event.button == MouseButton.LEFT):
            action()
            return None
        return NotImplemented
    return handler


class ScrollControl(FormattedTextControl):
    """Formatted text whose mouse wheel reports scroll steps."""

    def __init__(self, text, on_scroll, **options):
        super().__init__(text, **options)
        self.on_scroll = on_scroll

    def mouse_handler(self, mouse_event):
        if mouse_event.event_type == MouseEventType.SCROLL_UP:
            self.on_scroll(-3)
            return None
        if mouse_event.event_type == MouseEventType.SCROLL_DOWN:
            self.on_scroll(3)
            return None
        return super().mouse_handler(mouse_event)


def rounded_box(body, border_style, top_left=None, top_right=None, *, height=None, width=None):
    """A container framed by rounded corners with optional title fragments on top."""
    def line(left, right, leading, trailing):
        cells = [Window(width=1, height=1, char=left, style=border_style)]
        if leading is not None:
            cells.append(Window(FormattedTextControl(leading), dont_extend_width=True, height=1))
        cells.append(Window(height=1, char="─", style=border_style))
        if trailing is not None:
            cells.append(Window(FormattedTextControl(trailing), dont_extend_width=True, height=1))
        cells.append(Window(width=1, height=1, char=right, style=border_style))
        return VSplit(cells, height=1)

    side = lambda: Window(width=1, char="│", style=border_style)
    return HSplit([
        line("╭", "╮", top_left, top_right),
        VSplit([side(), body, side()]),
        line("╰", "╯", None, None),
    ], height=height, width=width)


def exact(size) -> Dimension:
    return Dimension.exact(max(0, int(size)))
