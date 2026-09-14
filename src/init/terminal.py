"""Rich terminal frame with nonblocking Windows input and media status."""

import asyncio
import io
import os
import sys
import threading
import time
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from datetime import datetime

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text


async def media_is_playing():
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as Manager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status,
    )
    manager = await Manager.request_async()
    return any(session.get_playback_info().playback_status == Status.PLAYING
               for session in manager.get_sessions())


class TerminalUI(io.TextIOBase):
    """Capture existing print/stream output inside one full-screen panel."""

    def __init__(self, console=None):
        self.console = console or Console(file=sys.stdout)
        self._lock = threading.RLock()
        self._output = ""
        self._layout_key = None
        self._layout_lines = []
        self._prompt = None
        self._input = ""
        self._cursor = 0
        self._history = []
        self._scroll = 0
        self.playing = False
        self._stop = threading.Event()
        self._stack = ExitStack()

    def writable(self):
        return True

    def isatty(self):
        return True

    @property
    def encoding(self):
        return "utf-8"

    def write(self, value):
        with self._lock:
            for part_index, part in enumerate(value.split("\r")):
                if part_index:
                    self._output = self._output.rpartition("\n")[0] + ("\n" if "\n" in self._output else "")
                self._output += part
            if len(self._output) > 100_000:
                self._output = self._output[-80_000:].partition("\n")[2]
        return len(value)

    def flush(self):
        pass

    def output_snapshot(self):
        with self._lock:
            return self._output

    def update_response(self, prefix, text):
        with self._lock:
            self._output = prefix + text

    def render(self):
        width, height = self.console.size
        with self._lock:
            output, prompt, value, cursor = self._output, self._prompt, self._input, self._cursor
            scroll, playing = self._scroll, self.playing
        inner_width = max(1, width - 4)
        input_lines = []
        if prompt is not None:
            entry = Text(prompt)
            entry.append(value[:cursor], style="green")
            entry.append(value[cursor:cursor + 1] or " ", style="green reverse")
            entry.append(value[cursor + 1:], style="green")
            input_lines = list(entry.wrap(self.console, inner_width))
            cursor_line = len(Text(prompt + value[:cursor]).wrap(self.console, inner_width)) - 1
            input_lines = input_lines[max(0, cursor_line - 2):max(3, cursor_line + 1)]
        available = max(0, height - 2 - len(input_lines))
        layout_key = (output, inner_width)
        if layout_key != self._layout_key:
            self._layout_lines = list(Text.from_ansi(output).wrap(self.console, inner_width))
            self._layout_key = layout_key
        lines = self._layout_lines
        scroll = min(scroll, max(0, len(lines) - available))
        end = len(lines) - scroll
        visible = lines[max(0, end - available):end] if available else []
        visible += [Text("")] * max(0, available - len(visible))
        title = Text(datetime.now().astimezone().strftime("%a %d/%m/%Y  %H:%M:%S"), style="bright_white")
        subtitle = None
        if playing:
            frames = ("▁▃▆█▅▂▁", "▃▆█▅▂▁▃", "▆█▅▂▁▃▆", "█▅▂▁▃▆█")
            subtitle = Text(frames[int(time.monotonic() * 6) % len(frames)], style="bright_white")
        return Panel(Group(*(visible + input_lines)), box=box.SQUARE,
                     border_style="bright_white", title=title, title_align="right",
                     subtitle=subtitle, subtitle_align="left", width=width,
                     height=height, padding=(0, 1))

    def _poll_media(self):
        async def poll():
            while not self._stop.is_set():
                try:
                    playing = await asyncio.wait_for(media_is_playing(), timeout=2)
                except Exception:
                    playing = False
                with self._lock:
                    self.playing = playing
                for _ in range(20):
                    if self._stop.is_set():
                        return
                    await asyncio.sleep(0.1)
        asyncio.run(poll())

    def __enter__(self):
        live = Live(console=self.console, screen=True, refresh_per_second=60,
                    get_renderable=self.render, redirect_stdout=False,
                    redirect_stderr=False, vertical_overflow="crop")
        try:
            self._stack.enter_context(live)
            self._stack.enter_context(redirect_stdout(self))
            self._stack.enter_context(redirect_stderr(self))
            self._worker = threading.Thread(target=self._poll_media, daemon=True)
            self._worker.start()
        except BaseException:
            self._stack.close()
            raise
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._worker.join(timeout=3)
        self._stack.close()

    def read_input(self, prompt):
        import msvcrt
        with self._lock:
            self._prompt, self._input, self._cursor, self._scroll = prompt, "", 0, 0
        history_index = len(self._history)
        draft = ""
        try:
            while True:
                if not msvcrt.kbhit():
                    time.sleep(0.005)
                    continue
                character = msvcrt.getwch()
                if character == "\x03":
                    raise KeyboardInterrupt
                if character == "\x1a":
                    raise EOFError
                if character in ("\r", "\n"):
                    with self._lock:
                        result = self._input
                    self.write(f"\x1b[0m{prompt}\x1b[32m{result}\x1b[0m\n")
                    if result:
                        self._history.append(result)
                    return result
                with self._lock:
                    if character in ("\x00", "\xe0"):
                        key = msvcrt.getwch()
                        if key == "K":
                            self._cursor = max(0, self._cursor - 1)
                        elif key == "M":
                            self._cursor = min(len(self._input), self._cursor + 1)
                        elif key == "G":
                            self._cursor = 0
                        elif key == "O":
                            self._cursor = len(self._input)
                        elif key == "S":
                            self._input = self._input[:self._cursor] + self._input[self._cursor + 1:]
                        elif key in ("H", "P"):
                            if history_index == len(self._history):
                                draft = self._input
                            history_index = max(0, min(len(self._history), history_index + (-1 if key == "H" else 1)))
                            self._input = self._history[history_index] if history_index < len(self._history) else draft
                            self._cursor = len(self._input)
                        elif key == "I":
                            self._scroll += max(1, self.console.height - 5)
                        elif key == "Q":
                            self._scroll = max(0, self._scroll - max(1, self.console.height - 5))
                    elif character == "\b":
                        if self._cursor:
                            self._input = self._input[:self._cursor - 1] + self._input[self._cursor:]
                            self._cursor -= 1
                    elif character >= " ":
                        self._input = self._input[:self._cursor] + character + self._input[self._cursor:]
                        self._cursor += 1
                        self._scroll = 0
        finally:
            with self._lock:
                self._prompt = None


def interactive_terminal():
    return (os.name == "nt" and sys.stdin.isatty() and
            sys.stdout.isatty() and os.environ.get("TERM") != "dumb")
