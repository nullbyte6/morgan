"""Rich terminal frame with nonblocking Windows input and media status."""

import asyncio
import io
import os
import queue
import sys
import threading
import time
import warnings
from contextlib import (
    ExitStack,
    contextmanager,
    redirect_stderr,
    redirect_stdout)

from datetime import datetime

from rich.console import Console, Group
from rich.live import Live
from rich.text import Text


async def media_is_playing():
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as Manager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status,
    )
    manager = await Manager.request_async()
    return any(session.get_playback_info().playback_status == Status.PLAYING
               for session in manager.get_sessions())


def spectrum_levels(audio, sample_rate=44100):
    """Measure seven frequency bands from output audio, preserving stereo energy."""
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
    rms = np.array(
        [np.sqrt(power[(frequencies >= low) & (frequencies < high)].sum())
         for low, high in zip(edges, edges[1:])])
    return np.clip((20 * np.log10(np.maximum(rms, 1e-8)) + 60) / 60, 0, 1)


class TerminalUI(io.TextIOBase):
    """Capture existing print/stream output inside one full-screen panel."""

    def __init__(self, console=None):
        self.console = console or Console(file=sys.stdout)
        self._lock = threading.RLock()
        self._output = ""
        self._banner = ""
        self._layout_key = None
        self._layout_lines = []
        self._prompt = None
        self._input = ""
        self._cursor = 0
        self._keys = queue.Queue()
        self._max_scroll = 0
        self._scroll = 0
        self.playing = False
        self._levels = (0.0,) * 7
        self._levels_at = 0.0
        self._audio_error = None
        self._stop = threading.Event()
        self._stack = ExitStack()
        self._live = None
        self._suspended = False

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
                    self._output = self._output.rpartition("\n")[0] + (
                        "\n" if "\n" in self._output else "")
                self._output += part
        return len(value)

    def flush(self):
        pass

    def output_snapshot(self):
        with self._lock:
            return self._output

    def set_banner(self, banner):
        """Keep startup artwork separate from the scrolling conversation."""
        with self._lock:
            self._banner = banner.rstrip("\n")

    def update_response(self, prefix, text):
        with self._lock:
            self._output = prefix + text

    def render(self):
        width, height = self.console.size
        with self._lock:
            output, prompt, value, cursor = self._output, self._prompt, self._input, self._cursor
            banner = self._banner
            scroll, playing = self._scroll, self.playing
            audio_error = self._audio_error
            levels = self._levels if time.monotonic() - self._levels_at < 0.5 else (0.0,) * 7
        inner_width = max(1, width - 4)
        input_lines = []
        if prompt is not None:
            entry = Text(prompt)
            entry.append(value[:cursor], style="green")
            entry.append(value[cursor:cursor + 1] or " ", style="green reverse")
            entry.append(value[cursor + 1:], style="green")
            input_lines = list(entry.wrap(self.console, inner_width))
            cursor_line = len(Text(prompt + value[:cursor]).wrap(self.console,
                                                                 inner_width)) - 1
            input_lines = input_lines[
                max(0, cursor_line - 2):max(3, cursor_line + 1)]
        meter = ("audio !" if audio_error else
                 "".join(" ▁▂▃▄▅▆▇█"[round(level * 8)] for level in levels)
                 if any(level >= 0.0625 for level in levels) else "")
        meter_lines = []
        if meter:
            meter_text = Text(meter, style="bright_white", justify="right")
            meter_text.truncate(inner_width, overflow="crop")
            meter_lines = [meter_text]
        available = max(0, height - 2 - len(input_lines) - len(meter_lines))
        layout_key = (output, inner_width)
        if layout_key != self._layout_key:
            previous_count = len(self._layout_lines)
            previous_key = self._layout_key
            self._layout_lines = list(
                Text.from_ansi(output).wrap(self.console, inner_width))
            self._layout_key = layout_key
            if previous_key is not None and previous_key[1] == inner_width:
                with self._lock:
                    if self._scroll:
                        self._scroll = max(0, self._scroll +
                                           len(self._layout_lines) - previous_count)
        lines = self._layout_lines
        with self._lock:
            self._max_scroll = max(0, len(lines) - available)
            self._scroll = min(self._scroll, self._max_scroll)
            scroll = self._scroll
        end = len(lines) - scroll
        visible = lines[max(0, end - available):end] if available else []
        spare = max(0, available - len(visible))
        backdrop = [Text("")] * spare
        if banner and spare:
            artwork = [Text(line.rstrip(), style="bright_white")
                       for line in banner.splitlines()]
            art_width = max((line.cell_len for line in artwork), default=0)
            left = max(0, (inner_width - art_width) // 2)
            top = max(0, (spare - len(artwork)) // 2)
            if len(artwork) <= spare:
                for index, line in enumerate(artwork):
                    line.pad_left(left)
                    line.truncate(inner_width, overflow="crop")
                    backdrop[top + index] = line
        visible = backdrop + visible

        header = Text(datetime.now().astimezone().strftime("%a %d/%m/%Y · %H:%M:%S"),
            style="bright_white",
            justify="right")

        footer = Text("↑/↓ · PgUp/PgDn", style="bright_white")
        return Group(header, *(visible + input_lines +
                               meter_lines), footer)

    def _poll_audio(self):
        """Read only speaker loopback in a worker; never block terminal rendering."""
        try:
            import soundcard as sc
        except ImportError as error:
            self._audio_error = str(error)
            return
        while not self._stop.is_set():
            try:
                speaker = sc.default_speaker()
                if speaker is None:
                    self._stop.wait(1)
                    continue
                loopback = sc.get_microphone(id=speaker.id,
                                             include_loopback=True)
                if not loopback.isloopback:
                    self._stop.wait(1)
                    continue
                with loopback.recorder(samplerate=44100,
                                       blocksize=8192) as recorder:
                    next_device_check = time.monotonic() + 2
                    while not self._stop.is_set():
                        with warnings.catch_warnings():
                            warnings.filterwarnings(
                                "ignore",
                                message=r"^data discontinuity in recording$",
                                category=Warning,
                                module=r"soundcard\.mediafoundation",
                            )
                            audio = recorder.record(numframes=4096)
                        levels = spectrum_levels(audio)
                        with self._lock:
                            self._audio_error = None
                            self._levels = tuple(max(float(new), old * 0.8)
                                                 for new, old in
                                                 zip(levels, self._levels))
                            self._levels_at = time.monotonic()
                        if time.monotonic() >= next_device_check:
                            current = sc.default_speaker()
                            if current is None or current.id != speaker.id:
                                break
                            next_device_check = time.monotonic() + 2
            except Exception as error:
                with self._lock:
                    self._audio_error = str(error)
                self._stop.wait(1)
            finally:
                with self._lock:
                    self._levels = (0.0,) * 7

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
                for _ in range(20):
                    if self._stop.is_set():
                        return
                    await asyncio.sleep(0.1)

        asyncio.run(poll())

    def _poll_input(self):
        try:
            while not self._stop.is_set():
                if self._suspended:
                    self._stop.wait(0.01)
                    continue

                for kind, value in self._console_input.poll():
                    if kind == "scroll":
                        if value in ("page_up", "page_down"):
                            value = max(1, self.console.height - 5) * (
                                1 if value == "page_up" else -1)

                        with self._lock:
                            self._scroll = max(0, min(
                                    self._max_scroll,
                                    self._scroll + value))
                    else:
                        for character in value:
                            self._keys.put(character)

                self._stop.wait(0.005)

        except Exception as error:
            self._keys.put(error)

    def _get_key(self):
        while True:
            try:
                value = self._keys.get(timeout=0.05)
            except queue.Empty:
                continue
            if isinstance(value, Exception):
                raise value
            return value

    def __enter__(self):
        self._live = Live(
            console=self.console,
            screen=True,
            refresh_per_second=60,
            get_renderable=self.render,
            redirect_stdout=False,
            redirect_stderr=False,
            vertical_overflow="crop")

        try:
            from .console_input import ConsoleInput
            self._console_input = ConsoleInput()
            self._stack.callback(self._console_input.close)
            self._stack.enter_context(self._live)
            self._input_worker = threading.Thread(target=self._poll_input,
                                                  daemon=True)
            self._input_worker.start()
            self._stack.enter_context(redirect_stdout(self))
            self._stack.enter_context(redirect_stderr(self))
            self._worker = threading.Thread(target=self._poll_media,
                                            daemon=True)
            self._worker.start()
            self._audio_worker = threading.Thread(target=self._poll_audio,
                                                  daemon=True)
            self._audio_worker.start()
        except BaseException:
            self._stop.set()
            self._stack.close()
            raise
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._input_worker.join(timeout=3)
        self._worker.join(timeout=3)
        self._audio_worker.join(timeout=3)
        self._stack.close()

    @contextmanager
    def suspend(self):
        """Temporarily give full control of the terminal to an external
        interactive application such as PyVim."""

        if self._suspended:
            yield
            return

        self._suspended = True

        old_stdout = sys.stdout
        old_stderr = sys.stderr

        try:
            if self._live is not None:
                self._live.stop()

            sys.stdout = self.console.file
            sys.stderr = sys.__stderr__
            sys.stdout.flush()
            sys.stderr.flush()
            yield

        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

            if self._live is not None:
                self._live.start(refresh=True)
            self._suspended = False

    def read_input(self, prompt):
        with self._lock:
            self._prompt, self._input, self._cursor = prompt, "", 0
        try:
            while True:
                character = self._get_key()
                if character == "\x03":
                    raise KeyboardInterrupt
                if character == "\x1a":
                    raise EOFError
                if character in ("\r", "\n"):
                    with self._lock:
                        result = self._input
                    self.write(f"\x1b[0m{prompt}\x1b[32m{result}\x1b[0m\n")
                    return result
                with self._lock:
                    if character in ("\x00", "\xe0"):
                        key = self._get_key()
                        if key == "K":
                            self._cursor = max(0, self._cursor - 1)
                        elif key == "M":
                            self._cursor = min(len(self._input),
                                               self._cursor + 1)
                        elif key == "G":
                            self._cursor = 0
                        elif key == "O":
                            self._cursor = len(self._input)
                        elif key == "S":
                            self._input = self._input[
                                              :self._cursor] + self._input[
                                              self._cursor + 1:]
                    elif character == "\b":
                        if self._cursor:
                            self._input = self._input[
                                              :self._cursor - 1] + self._input[
                                              self._cursor:]
                            self._cursor -= 1
                    elif character >= " ":
                        self._input = self._input[
                                          :self._cursor] + character + self._input[
                                          self._cursor:]
                        self._cursor += 1
                        self._scroll = 0
        finally:
            with self._lock:
                self._prompt = None


def interactive_terminal():
    return (os.name == "nt" and sys.stdin.isatty() and
            sys.stdout.isatty() and os.environ.get("TERM") != "dumb")
