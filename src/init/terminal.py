"""Arlo full-screen terminal UI using prompt_toolkit."""

import asyncio
import os
import re
import threading
import time
import warnings
from contextlib import contextmanager
from datetime import datetime

from prompt_toolkit import Application
from prompt_toolkit.application import run_in_terminal
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import ANSI, FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import (
    BufferControl,
    ConditionalContainer,
    FormattedTextControl,
    HSplit,
    Layout,
    Window)

from prompt_toolkit.styles import Style

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


async def media_is_playing():
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as Manager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status)

    manager = await Manager.request_async()
    return any(
        session.get_playback_info().playback_status == Status.PLAYING
        for session in manager.get_sessions())


def spectrum_levels(audio, sample_rate=44100):
    import numpy as np

    samples = np.asarray(audio)
    if samples.ndim == 1:
        samples = samples[:, None]

    if len(samples) < 2 or samples.shape[1] == 0:
        return np.zeros(7)

    window = np.hanning(len(samples))
    spectrum = np.abs(
        np.fft.rfft(samples * window[:, None], axis=0))

    power = np.mean(
        (spectrum / max(window.sum(), 1)) ** 2,
        axis=1)

    frequencies = np.fft.rfftfreq(
        len(samples),
        1 / sample_rate)

    edges = (
        0,
        125,
        250,
        500,
        1000,
        2000,
        4000,
        sample_rate / 2 + 1)

    rms = np.array([
        np.sqrt(
            power[
                (frequencies >= low)
                & (frequencies < high)
            ].sum())
        for low, high in zip(edges, edges[1:])
    ])

    return np.clip((20 * np.log10(np.maximum(rms, 1e-8)) + 60)
                   / 60, 0, 1)


class TerminalUI:
    def __init__(self):
        self._lock = threading.RLock()

        self._output = ""
        self._banner = ""
        self._prompt = ""
        self._placeholder = ""
        self._thinking = False

        self.playing = False
        self._levels = (0.0,) * 7
        self._levels_at = 0.0
        self._audio_error = None

        self._stop = threading.Event()
        self._input_done = threading.Event()
        self._input_result = ""

        self._buffer = Buffer(multiline=False)
        self._bindings = KeyBindings()

        self._create_keybindings()
        self._create_application()

    def _invalidate(self):
        app = getattr(self, "application", None)

        if app is not None and app.is_running:
            app.invalidate()

    def _create_keybindings(self):
        @self._bindings.add("enter")
        def _(event):
            self._input_result = self._buffer.text
            self._input_done.set()

        @self._bindings.add("c-c")
        def _(event):
            self._input_result = ""
            self._input_done.set()
            event.app.exit(exception=KeyboardInterrupt)

        @self._bindings.add("c-z")
        def _(event):
            self._input_result = ""
            self._input_done.set()
            event.app.exit(exception=EOFError)

    def _header(self):
        return datetime.now().astimezone().strftime(
            "%a %d/%m/%Y · %H:%M:%S"
        )

    def _body(self):
        with self._lock:
            output = self._output
            banner = self._banner

        if output:
            return ANSI(output)

        if banner:
            return FormattedText([
                ("class:banner", banner)
            ])

        return ""

    def _thinking_text(self):
        if self._thinking:
            return FormattedText([
                ("class:dim", "Pensando")
            ])

        return ""

    def _prompt_text(self):
        with self._lock:
            prompt = self._prompt
            placeholder = self._placeholder
            empty = not self._buffer.text

        if empty and placeholder:
            return FormattedText([
                ("", prompt),
                ("class:placeholder", placeholder),
            ])

        return FormattedText([
            ("", prompt)
        ])

    def _meter(self):
        with self._lock:
            audio_error = self._audio_error
            levels = (
                self._levels
                if time.monotonic() - self._levels_at < 0.5
                else (0.0,) * 7)

        if audio_error:
            return "audio !"

        if not any(level >= 0.0625 for level in levels):
            return ""

        return "".join(
            " ▁▂▃▄▅▆▇█"[round(level * 8)]
            for level in levels
        )

    def _create_application(self):
        body = Window(
            content=FormattedTextControl(
                text=self._body,
                focusable=False),
            wrap_lines=True,
            always_hide_cursor=True)

        thinking = ConditionalContainer(
            content=Window(
                FormattedTextControl(
                    text=self._thinking_text), height=1),
            filter=Condition(
                lambda: self._thinking))

        prompt = Window(
            content=FormattedTextControl(
                text=self._prompt_text),
            height=1)

        input_window = Window(
            content=BufferControl(
                buffer=self._buffer),
            height=1)

        meter = Window(
            content=FormattedTextControl(
                text=self._meter),
            height=1,
            dont_extend_height=True)

        header = Window(
            content=FormattedTextControl(
                text=self._header),
            height=1,
            align="RIGHT")

        footer = Window(
            content=FormattedTextControl(
                text=lambda: "↑/↓ · PgUp/PgDn"),
            height=1)

        root = HSplit([
            header,
            body,
            thinking,
            prompt,
            input_window,
            meter,
            footer,
        ])

        self.application = Application(
            layout=Layout(
                root,
                focused_element=input_window),
            key_bindings=self._bindings,
            full_screen=True,
            mouse_support=False,
            style=Style.from_dict({
                "banner": "fg:#ffffff",
                "placeholder": "italic fg:#666666",
                "dim": "fg:#666666",
            }), refresh_interval=1.0)

    def write(self, value):
        with self._lock:
            for part_index, part in enumerate(
                value.split("\r")):
                if part_index:
                    before, separator, _ = (self._output.rpartition("\n"))
                    self._output = (before + separator)

                self._output += part

        self._invalidate()
        return len(value)

    def flush(self):
        pass

    def output_snapshot(self):
        with self._lock:
            return self._output

    def set_banner(self, banner):
        with self._lock:
            self._banner = banner.rstrip("\n")

        self._invalidate()

    def set_thinking(self, thinking: bool):
        with self._lock:
            self._thinking = thinking

        self._invalidate()

    def update_response(self, prefix, text):
        with self._lock:
            self._output = prefix + text

        self._invalidate()

    def read_input(self, prompt, placeholder=""):
        with self._lock:
            self._prompt = prompt
            self._placeholder = placeholder

        self._buffer.reset()
        self._input_result = ""
        self._input_done.clear()
        self._invalidate()

        self._input_done.wait()

        result = self._input_result

        self.write(
            f"\x1b[0m{prompt}"
            f"\x1b[32m{result}"
            f"\x1b[0m\n" )

        with self._lock:
            self._prompt = ""
            self._placeholder = ""

        return result

    def _poll_audio(self):
        try:
            import soundcard as sc
        except ImportError as error:
            self._audio_error = str(error)
            self._invalidate()
            return

        while not self._stop.is_set():
            try:
                speaker = sc.default_speaker()

                if speaker is None:
                    self._stop.wait(1)
                    continue

                loopback = sc.get_microphone(
                    id=speaker.id,
                    include_loopback=True)

                if not loopback.isloopback:
                    self._stop.wait(1)
                    continue

                with loopback.recorder(
                    samplerate=44100,
                    blocksize=8192) as recorder:

                    next_device_check = (time.monotonic() + 2)

                    while not self._stop.is_set():
                        with warnings.catch_warnings():
                            warnings.filterwarnings(
                                "ignore",
                                message=(r"^data discontinuity "
                                    r"in recording$"),
                                category=Warning,
                                module=(r"soundcard"
                                    r"\.mediafoundation"))

                            audio = recorder.record(numframes=4096)

                        levels = spectrum_levels(audio)

                        with self._lock:
                            self._audio_error = None
                            self._levels = tuple(
                                max(float(new), old * 0.8)
                                for new, old in zip(
                                    levels, self._levels))

                            self._levels_at = (
                                time.monotonic())

                        self._invalidate()

                        if (time.monotonic()
                            >= next_device_check):
                            current = (
                                sc.default_speaker())

                            if (current is None
                                or current.id
                                != speaker.id):
                                break

                            next_device_check = (
                                time.monotonic() + 2)

            except Exception as error:
                with self._lock:
                    self._audio_error = str(error)

                self._invalidate()
                self._stop.wait(1)

            finally:
                with self._lock:
                    self._levels = (0.0,) * 7

    def _poll_media(self):
        async def poll():
            while not self._stop.is_set():
                try:
                    playing = await asyncio.wait_for(
                        media_is_playing(),
                        timeout=2)

                except Exception:
                    playing = False

                with self._lock:
                    self.playing = playing

                self._invalidate()

                for _ in range(20):
                    if self._stop.is_set():
                        return

                    await asyncio.sleep(0.1)

        asyncio.run(poll())

    def __enter__(self):
        self._stop.clear()

        self._media_worker = threading.Thread(
            target=self._poll_media,
            daemon=True)
        self._media_worker.start()

        self._audio_worker = threading.Thread(
            target=self._poll_audio,
            daemon=True)
        self._audio_worker.start()

        self._app_worker = threading.Thread(
            target=self.application.run,
            daemon=True)
        self._app_worker.start()

        return self

    def __exit__(self, *exc):
        self._stop.set()

        if self.application.is_running:
            self.application.exit()

        self._media_worker.join(timeout=3)
        self._audio_worker.join(timeout=3)
        self._app_worker.join(timeout=3)

    @contextmanager
    def suspend(self):
        if not self.application.is_running:
            yield
            return

        with run_in_terminal(
            lambda: None,
            in_executor=False,
        ):
            yield


def interactive_terminal():
    return (
        os.name == "nt"
        and sys.stdin.isatty()
        and sys.stdout.isatty()
        and os.environ.get("TERM") != "dumb"
    )