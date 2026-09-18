"""Arlo full-screen terminal UI using Rich."""

import asyncio
import os
import re
import shutil
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime

from rich.align import Align
from rich.console import Console, Group
from rich.live import Live
from rich.text import Text

from src.init.console_input import ConsoleInput

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
RICH_FOREGROUND_COLOR = "white"
RICH_DIM_COLOR = "bright_black"
RICH_USER_COLOR = "green"


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

    band_count = 15

    if len(samples) < 2 or samples.shape[1] == 0:
        return np.zeros(band_count)

    window = np.hanning(len(samples))
    spectrum = np.abs(
        np.fft.rfft(samples * window[:, None], axis=0))

    power = np.mean(
        (spectrum / max(window.sum(), 1)) ** 2,
        axis=1)

    frequencies = np.fft.rfftfreq(
        len(samples),
        1 / sample_rate)

    edges = np.geomspace(60,
        min(12000, sample_rate / 2),
        band_count + 1)

    rms = np.array([
        np.sqrt(power[
                (frequencies >= low) &
                (frequencies < high)
            ].sum()) for low, high in zip(edges, edges[1:])])

    return np.clip((20 * np.log10(np.maximum(rms, 1e-8)) + 60) / 60, 0, 1)

# noinspection PyBroadException
class TerminalUI:
    def __init__(self):
        self.console = Console(highlight=False)
        self.console_input = None
        self.live = None

        self._lock = threading.RLock()
        self._banner = ""
        self._prompt = ""
        self._placeholder = ""
        self._input = ""
        self._cursor = 0
        self._thinking = False
        self._reading_input = False

        self.playing = False
        self._levels = (0.0,) * 15
        self._levels_at = 0.0

        self._stop = threading.Event()
        self._input_done = threading.Event()
        self._input_result = ""

        self._media_worker = None
        self._input_worker = None

        self._version = ""

    def set_version(self, version: str):
        with self._lock:
            self._version = ANSI_RE.sub("", version).strip()
        self._refresh()

    def _refresh(self):
        live = self.live
        if live is not None:
            try:
                live.update(self.render(), refresh=True)
            except Exception:
                pass

    def _header(self, width):
        value = datetime.now().astimezone().strftime("%a %d/%m/%Y · %H:%M:%S")
        return Align.right(Text(value, style=RICH_FOREGROUND_COLOR),
                           width=width)

    def _banner_renderable(self):
        with self._lock:
            banner = self._banner

        if not banner:
            return Text("")

        return Align.center(Text(banner, style=f"bold {RICH_FOREGROUND_COLOR}"))

    def _input_renderable(self):
        with self._lock:
            prompt = self._prompt
            placeholder = self._placeholder
            value = self._input
            cursor = self._cursor

        line = Text()
        line.append(ANSI_RE.sub("", prompt), style=RICH_FOREGROUND_COLOR)

        if value:
            line.append(value[:cursor], style=RICH_USER_COLOR)
            line.append("▇", style=RICH_USER_COLOR)
            line.append(value[cursor:], style=RICH_USER_COLOR)
        else:
            line.append("▇", style=RICH_USER_COLOR)
            if placeholder:
                line.append(placeholder, style=f"italic {RICH_DIM_COLOR}")

        return line

    def _meter_renderable(self, width):
        with self._lock:
            levels = (
                self._levels
                if time.monotonic() - self._levels_at < 0.5
                else (0.0,) * 15
            )

        style = RICH_FOREGROUND_COLOR
        activity = max(levels, default=0.0)
        if activity < 0.08:
            idle = "─" * 31

            return Group(
                Align.center(Text(""), width=width),
                Align.center(Text(idle, style=RICH_DIM_COLOR), width=width),
                Align.center(Text(""), width=width),
            )

        top = []
        middle = []
        bottom = []

        for level in levels:
            level = min(1.0, level * 1.35)

            if level < 0.12:
                top.append(" ")
                middle.append("─")
                bottom.append(" ")

            elif level < 0.35:
                top.append(" ")
                middle.append("━")
                bottom.append(" ")

            elif level < 0.65:
                top.append("▄")
                middle.append("█")
                bottom.append("▀")

            else:
                top.append("█")
                middle.append("█")
                bottom.append("█")

        return Group(
            Align.center(Text(" ".join(top), style=style), width=width),
            Align.center(Text(" ".join(middle), style=style), width=width),
            Align.center(Text(" ".join(bottom), style=style), width=width))


    def render(self):
        terminal = shutil.get_terminal_size((120, 30))
        width = max(20, terminal.columns)
        height = max(8, terminal.lines)

        with self._lock:
            thinking = self._thinking
            has_prompt = self._reading_input
            banner = self._banner
            version = self._version

        version_height = 1
        status_height = 1
        input_height = 1

        bottom_height = version_height + status_height + input_height
        main_height = max(1, height - bottom_height - 1)

        banner_height = (
            len(banner.rstrip("\n").splitlines())
            if banner else 0)

        meter_height = 3
        spacer_height = 1
        visual_height = (banner_height + spacer_height + meter_height)

        body = []

        if banner and visual_height <= main_height:
            free_height = max(0, main_height - visual_height)
            top = free_height // 2
            bottom = free_height - top
            body.extend(Text() for _ in range(top))
            body.append(self._banner_renderable())
            body.append(Text(""))
            body.append(self._meter_renderable(width))
            body.extend(Text() for _ in range(bottom))
        else:
            body.extend(Text() for _ in range(main_height))

        renderables = [
            self._header(width),
            *body,
            Text(""),
            Text("Pensando" if thinking else "", style=RICH_DIM_COLOR),
            Text(version, style=RICH_DIM_COLOR),
            self._input_renderable() if has_prompt else Text(""),
        ]

        return Group(*renderables)

    def set_banner(self, banner):
        with self._lock:
            self._banner = banner.rstrip("\n")
        self._refresh()

    def set_thinking(self, thinking: bool):
        with self._lock:
            self._thinking = thinking

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
                    self._input = self._input[:self._cursor - 1] + self._input[
                        self._cursor:]
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
                    self._input = self._input[:self._cursor] + self._input[
                        self._cursor + 1:]

            elif key >= " " and key != "\x7f":
                self._input = self._input[:self._cursor] + key + self._input[
                    self._cursor:]
                self._cursor += len(key)

        self._refresh()

    def read_input(self, prompt, placeholder=""):
        with self._lock:
            self._reading_input = True
            self._prompt = prompt
            self._placeholder = placeholder
            self._input = ""
            self._cursor = 0
            self._input_result = ""
            self._input_done.clear()

        self._refresh()
        self._input_done.wait()

        with self._lock:
            result = self._input_result
            self._reading_input = False
            self._prompt = ""
            self._placeholder = ""
            self._input = ""
            self._cursor = 0

        if result == "" and self._stop.is_set():
            raise EOFError

        return result

    def update_audio_levels(self, samples, sample_rate):
        levels = spectrum_levels(samples, sample_rate)
        with self._lock:
            self._levels = tuple(max(float(new), old * 0.8) for new, old in
                                 zip(levels, self._levels))
            self._levels_at = time.monotonic()
        self._refresh()

    def clear_audio_levels(self):
        with self._lock:
            self._levels = (0.0,) * 15
        self._refresh()

    def _poll_input(self):
        while not self._stop.is_set():
            try:
                events = self.console_input.poll()

                for event_type, value in events:
                    if event_type == "key":
                        self._handle_key(value)

            except Exception:
                if self._stop.is_set():
                    return

            time.sleep(0.01)

    def _poll_media(self):
        async def poll():
            while not self._stop.is_set():
                try:
                    playing = await asyncio.wait_for(media_is_playing(),
                                                     timeout=2)
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

        self.live = Live(
            self.render(),
            console=self.console,
            screen=True,
            refresh_per_second=20,
            auto_refresh=True,
            redirect_stdout=False,
            redirect_stderr=False,
            vertical_overflow="crop",
        )

        self.live.start(refresh=True)

        self._input_worker = threading.Thread(
            target=self._poll_input,
            daemon=True)
        self._input_worker.start()

        self._media_worker = threading.Thread(
            target=self._poll_media,
            daemon=True)
        self._media_worker.start()

        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._input_done.set()

        if self._input_worker is not None:
            self._input_worker.join(timeout=1)

        if self._media_worker is not None:
            self._media_worker.join(timeout=3)

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
