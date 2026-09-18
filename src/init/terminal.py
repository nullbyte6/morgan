"""Arlo full-screen terminal UI using Rich."""

import asyncio
import os
import re
import shutil
import sys
import threading
import time
import warnings
from contextlib import contextmanager
from datetime import datetime

from rich.align import Align
from rich.console import Console, Group
from rich.live import Live
from rich.text import Text

from src.init import colors
from src.init.console_input import ConsoleInput

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
BANNER_COLOR = colors.RESET_COLOR
DIM_COLOR = colors.ASSISTANT_COLOR
USER_COLOR = colors.USER_COLOR

async def media_is_playing():
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as Manager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status)

    manager = await Manager.request_async()
    return any(session.get_playback_info().playback_status == Status.PLAYING
               for session in manager.get_sessions())


def spectrum_levels(audio, sample_rate=44100):
    import numpy as np

    samples = np.asarray(audio)
    if samples.ndim == 1:
        samples = samples[:, None]

    if len(samples) < 2 or samples.shape[1] == 0:
        return np.zeros(7)

    window = np.hanning(len(samples))
    spectrum = np.abs(np.fft.rfft(samples * window[:, None], axis=0))
    power = np.mean((spectrum / max(window.sum(), 1)) ** 2, axis=1)
    frequencies = np.fft.rfftfreq(len(samples), 1 / sample_rate)
    edges = (0, 125, 250, 500, 1000, 2000, 4000, sample_rate / 2 + 1)

    rms = np.array([
        np.sqrt(power[(frequencies >= low) & (frequencies < high)].sum())
        for low, high in zip(edges, edges[1:])
    ])

    return np.clip((20 * np.log10(np.maximum(rms, 1e-8)) + 60) / 60, 0, 1)


class TerminalUI:
    def __init__(self):
        self.console = Console(highlight=False)
        self.console_input = None
        self.live = None

        self._lock = threading.RLock()
        self._output = ""
        self._banner = ""
        self._prompt = ""
        self._placeholder = ""
        self._input = ""
        self._cursor = 0
        self._thinking = False

        self._scroll_offset = 0
        self._follow_output = True

        self.playing = False
        self._levels = (0.0,) * 7
        self._levels_at = 0.0
        self._audio_error = None

        self._stop = threading.Event()
        self._input_done = threading.Event()
        self._input_result = ""

        self._media_worker = None
        self._audio_worker = None
        self._input_worker = None

    def _refresh(self):
        live = self.live
        if live is not None:
            try:
                live.refresh()
            except Exception:
                pass

    @staticmethod
    def _visible_length(value):
        return len(ANSI_RE.sub("", value))

    @staticmethod
    def _wrapped_height(value, width):
        if not value:
            return 0

        width = max(1, width)
        height = 0

        for line in ANSI_RE.sub("", value).splitlines() or [""]:
            height += max(1, (len(line) + width - 1) // width)

        return height

    def _header(self, width):
        value = datetime.now().astimezone().strftime("%a %d/%m/%Y · %H:%M:%S")
        return Align.right(Text(value, style=DIM_COLOR), width=width)

    def _banner_renderable(self):
        with self._lock:
            banner = self._banner

        if not banner:
            return Text("")

        return Align.center(Text(banner, style=f"bold {BANNER_COLOR}"))

    def _input_renderable(self):
        with self._lock:
            prompt = self._prompt
            placeholder = self._placeholder
            value = self._input
            cursor = self._cursor

        line = Text()
        line.append(ANSI_RE.sub("", prompt))

        if value:
            before = value[:cursor]
            character = value[cursor:cursor + 1]
            after = value[cursor + 1:]

            line.append(before, style=USER_COLOR)

            if character:
                line.append(character, style=f"reverse {USER_COLOR}")
                line.append(after, style=USER_COLOR)
            else:
                line.append(" ", style=f"reverse {USER_COLOR}")
        elif placeholder:
            line.append(placeholder, style=f"italic {DIM_COLOR}")
            line.append(" ", style="reverse")
        else:
            line.append(" ", style="reverse")

        return line

    def _meter_renderable(self, width):
        with self._lock:
            audio_error = self._audio_error
            levels = self._levels if time.monotonic() - self._levels_at < 0.5 else (0.0,) * 7

        if audio_error:
            value = Text("audio !", style=DIM_COLOR)
        elif any(level >= 0.0625 for level in levels):
            value = Text("".join(" ▁▂▃▄▅▆▇█"[round(level * 8)] for level in levels),
                         style=USER_COLOR)
        else:
            value = Text("")

        return Align.right(value, width=width)

    def _footer(self, width):
        return Align.right(Text("↑/↓ · PgUp/PgDn", style=DIM_COLOR), width=width)

    def _output_lines(self, width):
        with self._lock:
            output = self._output

        if not output:
            return []

        text = Text.from_ansi(output)
        lines = text.wrap(self.console, max(1, width), overflow="fold", no_wrap=False)
        return lines

    def _viewport(self, lines, height):
        if height <= 0 or not lines:
            return []

        with self._lock:
            max_offset = max(0, len(lines) - height)
            self._scroll_offset = min(self._scroll_offset, max_offset)
            offset = self._scroll_offset

        end = len(lines) - offset
        start = max(0, end - height)
        return lines[start:end]

    def render(self):
        terminal = shutil.get_terminal_size((120, 30))
        width = max(20, terminal.columns)
        height = max(8, terminal.lines)

        with self._lock:
            thinking = self._thinking
            has_prompt = bool(self._prompt)

        header_height = 1
        thinking_height = 1 if thinking else 0
        input_height = 1 if has_prompt else 0
        meter_height = 1
        footer_height = 1
        fixed_bottom = thinking_height + input_height + meter_height + footer_height

        content_height = max(0, height - header_height - fixed_bottom)
        output_lines = self._output_lines(width)

        banner = self._banner_renderable()
        banner_height = len(self._banner.rstrip("\n").splitlines()) if self._banner else 0

        output_needed = min(len(output_lines), content_height)
        free_height = max(0, content_height - output_needed)

        show_banner = bool(self._banner and banner_height and free_height >= banner_height + 2)

        body = []

        if show_banner:
            available_above_output = max(0, content_height - output_needed)
            top = max(0, (content_height - banner_height) // 2)
            top = min(top, max(0, available_above_output - banner_height))
            bottom = max(0, available_above_output - top - banner_height)

            if top:
                body.append(Text("\n" * top))

            body.append(banner)

            if bottom:
                body.append(Text("\n" * bottom))

            viewport_height = output_needed
        else:
            viewport_height = content_height

        viewport = self._viewport(output_lines, viewport_height)

        if viewport:
            body.extend(viewport)

        used = (banner_height if show_banner else 0) + len(viewport)

        if show_banner:
            used += max(0, content_height - output_needed - banner_height)

        if not show_banner and used < content_height:
            body.insert(0, Text("\n" * (content_height - used)))

        renderables = [self._header(width)]

        if body:
            renderables.extend(body)

        if thinking:
            renderables.append(Text("Pensando", style=DIM_COLOR))

        if has_prompt:
            renderables.append(self._input_renderable())

        renderables.append(self._meter_renderable(width))
        renderables.append(self._footer(width))

        return Group(*renderables)

    def write(self, value):
        with self._lock:
            for part_index, part in enumerate(value.split("\r")):
                if part_index:
                    before, separator, _ = self._output.rpartition("\n")
                    self._output = before + separator

                self._output += part

            if self._follow_output:
                self._scroll_offset = 0

        self._refresh()
        return len(value)

    def flush(self):
        pass

    def output_snapshot(self):
        with self._lock:
            return self._output

    def set_banner(self, banner):
        with self._lock:
            self._banner = banner.rstrip("\n")

        self._refresh()

    def set_thinking(self, thinking: bool):
        with self._lock:
            self._thinking = thinking

        self._refresh()

    def update_response(self, prefix, text):
        with self._lock:
            self._output = prefix + text

            if self._follow_output:
                self._scroll_offset = 0

        self._refresh()

    def _scroll(self, amount):
        terminal = shutil.get_terminal_size((120, 30))
        page = max(1, terminal.lines - 6)

        with self._lock:
            lines = self._output_lines(max(20, terminal.columns))
            maximum = max(0, len(lines) - 1)

            if amount == "page_up":
                self._scroll_offset = min(maximum, self._scroll_offset + page)
            elif amount == "page_down":
                self._scroll_offset = max(0, self._scroll_offset - page)
            elif amount > 0:
                self._scroll_offset = min(maximum, self._scroll_offset + amount)
            else:
                self._scroll_offset = max(0, self._scroll_offset + amount)

            self._follow_output = self._scroll_offset == 0

        self._refresh()

    def _handle_key(self, key):
        with self._lock:
            if key in ("\r", "\n"):
                self._input_result = self._input
                self._input_done.set()
                return

            if key == "\x03":
                self._input_result = ""
                self._input_done.set()
                return

            if key == "\x1a":
                self._input_result = ""
                self._input_done.set()
                return

            if key == "\x08":
                if self._cursor:
                    self._input = self._input[:self._cursor - 1] + self._input[self._cursor:]
                    self._cursor -= 1

            elif key == "\xe0K":
                self._cursor = max(0, self._cursor - 1)

            elif key == "\xe0M":
                self._cursor = min(len(self._input), self._cursor + 1)

            elif key == "\xe0G":
                self._cursor = 0

            elif key == "\xe0O":
                self._cursor = len(self._input)

            elif key == "\xe0S":
                if self._cursor < len(self._input):
                    self._input = self._input[:self._cursor] + self._input[self._cursor + 1:]

            elif key >= " " and key != "\x7f":
                self._input = self._input[:self._cursor] + key + self._input[self._cursor:]
                self._cursor += len(key)

        self._refresh()

    def _poll_input(self):
        while not self._stop.is_set():
            try:
                events = self.console_input.poll()

                for event_type, value in events:
                    if event_type == "scroll":
                        self._scroll(value)
                    elif event_type == "key":
                        self._handle_key(value)

            except Exception:
                if not self._stop.is_set():
                    time.sleep(0.05)

            self._stop.wait(0.01)

    def read_input(self, prompt, placeholder=""):
        with self._lock:
            self._prompt = prompt
            self._placeholder = placeholder
            self._input = ""
            self._cursor = 0
            self._input_result = ""
            self._input_done.clear()
            self._follow_output = True
            self._scroll_offset = 0

        self._refresh()
        self._input_done.wait()

        with self._lock:
            result = self._input_result
            self._prompt = ""
            self._placeholder = ""
            self._input = ""
            self._cursor = 0

        if result == "" and self._stop.is_set():
            raise EOFError

        self.write(f"\x1b[0m{prompt}\x1b[38;2;166;227;161m{result}\x1b[0m\n")
        return result

    def _poll_audio(self):
        try:
            import soundcard as sc
        except ImportError as error:
            self._audio_error = str(error)
            self._refresh()
            return

        while not self._stop.is_set():
            try:
                speaker = sc.default_speaker()

                if speaker is None:
                    self._stop.wait(1)
                    continue

                loopback = sc.get_microphone(id=speaker.id, include_loopback=True)

                if not loopback.isloopback:
                    self._stop.wait(1)
                    continue

                with loopback.recorder(samplerate=44100, blocksize=8192) as recorder:
                    next_device_check = time.monotonic() + 2

                    while not self._stop.is_set():
                        with warnings.catch_warnings():
                            warnings.filterwarnings("ignore",
                                message=r"^data discontinuity in recording$",
                                category=Warning,
                                module=r"soundcard\.mediafoundation")
                            audio = recorder.record(numframes=4096)

                        levels = spectrum_levels(audio)

                        with self._lock:
                            self._audio_error = None
                            self._levels = tuple(max(float(new), old * 0.8)
                                                 for new, old in zip(levels, self._levels))
                            self._levels_at = time.monotonic()

                        self._refresh()

                        if time.monotonic() >= next_device_check:
                            current = sc.default_speaker()

                            if current is None or current.id != speaker.id:
                                break

                            next_device_check = time.monotonic() + 2

            except Exception as error:
                with self._lock:
                    self._audio_error = str(error)

                self._refresh()
                self._stop.wait(1)

            finally:
                with self._lock:
                    self._levels = (0.0,) * 7

    def _poll_media(self):
        async def poll():
            while not self._stop.is_set():
                try:
                    playing = await asyncio.wait_for(media_is_playing(), timeout=2)
                except Exception:
                    playing = False

                with self._lock:
                    self.playing = playing

                self._refresh()

                for _ in range(20):
                    if self._stop.is_set():
                        return

                    await asyncio.sleep(0.1)

        asyncio.run(poll())

    def __enter__(self):
        self._stop.clear()
        self.console_input = ConsoleInput()

        self.live = Live(self.render(), console=self.console, screen=True,
                         refresh_per_second=30, auto_refresh=True,
                         redirect_stdout=False, redirect_stderr=False,
                         vertical_overflow="crop")

        self.live.start(refresh=True)

        self._input_worker = threading.Thread(target=self._poll_input, daemon=True)
        self._media_worker = threading.Thread(target=self._poll_media, daemon=True)
        self._audio_worker = threading.Thread(target=self._poll_audio, daemon=True)

        self._input_worker.start()
        self._media_worker.start()
        self._audio_worker.start()

        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._input_done.set()

        if self._input_worker is not None:
            self._input_worker.join(timeout=2)

        if self._media_worker is not None:
            self._media_worker.join(timeout=3)

        if self._audio_worker is not None:
            self._audio_worker.join(timeout=3)

        if self.live is not None:
            try:
                self.live.stop()
            except Exception:
                pass

        if self.console_input is not None:
            try:
                self.console_input.close()
            except Exception:
                pass

    @contextmanager
    def suspend(self):
        live = self.live
        console_input = self.console_input

        if live is None or console_input is None:
            yield
            return

        live.stop()

        try:
            console_input.suspend()
            yield
        finally:
            console_input.resume()
            live.start(refresh=True)

    def start_conversation(self):
        pass


def interactive_terminal():
    return (os.name == "nt"
            and sys.stdin.isatty()
            and sys.stdout.isatty()
            and os.environ.get("TERM") != "dumb")