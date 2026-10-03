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

from __future__ import annotations

import logging
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import Future
from logging.handlers import RotatingFileHandler
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.init.lang import SPEECH_LANGUAGES, get_language, tr
from src.init.voice import transcribe_voice
from src.init.voice_ipc import (
    WAKE_RECORD_REQUEST,
    ProcessLock,
    WakeInbox,
    audio_requested,
    voice_directory,
)
from src.init.identity import (
    get_assistant_environment,
    get_assistant_identifier,
    get_assistant_installation,
    get_assistant_name,
)
from src.init.wake_capture import BLOCK_SECONDS, SAMPLE_RATE, WakeCapture, WakeSettings
from src.platforms import current_platform

ROOT = Path(__file__).resolve().parent.parent

logging.basicConfig(
    level=logging.INFO,
    format="[Wake] %(message)s")

log = logging.getLogger(f"{get_assistant_identifier()}.wake")


def prioritize_listener() -> None:
    """Keep foreground UI rendering from starving wake audio/inference."""
    try:
        current_platform().raise_priority(process=True)
    except OSError:
        log.exception("Unable to raise wake-listener priority")


def is_assistant_running() -> bool:
    """Check the lifetime lock without activating or launching the desktop."""
    lock = ProcessLock("desktop-running")
    if not lock.acquire():
        return True
    lock.release()
    return False


def resolve_launcher() -> Path | None:
    """Prefer the installed executable named by <NAME>, then the repository launcher."""
    return current_platform().desktop_launcher(get_assistant_installation(), ROOT)


def launch_assistant() -> None:
    """Start the desktop without waiting for its services or UI."""
    launcher = resolve_launcher()
    if launcher is None or not launcher.exists():
        log.error(tr("wake.launcher_not_found", path=launcher))
        return
    if is_assistant_running():
        return

    log.info(tr("wake.activation_detected"))
    command, directory = current_platform().launch_command(launcher, ROOT)
    subprocess.Popen(
        command,
        cwd=str(directory),
        creationflags=current_platform().no_window_flags,
    )


class Recognizer:
    """One model, one inference at a time; audio never waits for transcription."""

    def __init__(self, model):
        self.model = model
        self.future = None

    def available(self):
        return self.future is None or self.future.done()

    def submit(self, snapshot, sample_rate=SAMPLE_RATE):
        future = self.future = Future()

        def recognize():
            try:
                text, _ = transcribe_voice(
                    snapshot.pcm, sample_rate, model=self.model,
                    language=None if snapshot.final else SPEECH_LANGUAGES[get_language()],
                    beam_size=5 if snapshot.final else 1,
                    vad_filter=snapshot.final)
                future.set_result(text)
            except Exception as error:
                future.set_exception(error)

        threading.Thread(target=recognize, name="wake-stt", daemon=True).start()
        return future


def capture_wake_word(recognizer, settings):
    """Return as soon as a wake phrase is heard, releasing input to desktop."""
    import sounddevice as sd

    device = sd.query_devices(kind="input")
    preferred_host = current_platform().preferred_audio_host
    if preferred_host:
        host_apis = sd.query_hostapis()
        for index, candidate in enumerate(sd.query_devices()):
            host_name = host_apis[candidate["hostapi"]]["name"]
            if (candidate["max_input_channels"] >= 1 and
                    candidate["name"] == device["name"] and
                    host_name == preferred_host):
                device = dict(candidate, index=index)
                break
    sample_rate = int(device.get("default_samplerate") or SAMPLE_RATE)
    frames = queue.Queue(maxsize=50)
    overflow = threading.Event()
    capture = WakeCapture(settings)
    job = None
    last_frame = time.monotonic()

    def receive(data, count, timing, status):
        if status:
            overflow.set()
        try:
            frames.put_nowait(bytes(data))
        except queue.Full:
            overflow.set()

    with sd.RawInputStream(samplerate=sample_rate,
                           blocksize=int(sample_rate * BLOCK_SECONDS),
                           device=device["index"], channels=1,
                           dtype="int16", callback=receive):
        while not audio_requested():
            try:
                pcm = frames.get(timeout=0.2)
            except queue.Empty:
                if time.monotonic() - last_frame > 5:
                    raise TimeoutError("Microphone stopped providing audio")
                continue
            last_frame = time.monotonic()
            if overflow.is_set():
                overflow.clear()
                capture = WakeCapture(settings)
                job = None
                while True:
                    try:
                        frames.get_nowait()
                    except queue.Empty:
                        break
                log.warning("Audio input overflow; wake capture reset")
                continue
            capture.feed(pcm)
            if job is not None:
                snapshot, future, started = job
                if future.done():
                    command = capture.accept_transcript(snapshot, future.result())
                    job = None
                    if command:
                        return False
                elif time.monotonic() - started > settings.recognition_seconds:
                    raise TimeoutError("Wake transcription timed out")
            if capture.event == "activated":
                return not audio_requested()
            elif capture.event in ("timeout", "too_long"):
                log.info("Wake capture ended: %s", capture.event)
                capture = WakeCapture(settings)
            if job is None and recognizer.available():
                snapshot = capture.next_transcription()
                if snapshot is not None:
                    job = (snapshot, recognizer.submit(snapshot, sample_rate),
                           time.monotonic())
    return None


def main() -> None:
    singleton = ProcessLock("wake-listener")
    if not singleton.acquire():
        return
    prioritize_listener()
    microphone = ProcessLock("microphone")
    try:
        handler = RotatingFileHandler(voice_directory() / "wake.log",
                                      maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(handler)
        run_listener(microphone)
    finally:
        microphone.release()
        singleton.release()


def run_listener(microphone):
    from faster_whisper import WhisperModel

    settings = WakeSettings.from_environment()
    inbox = None
    log.info(tr("wake.loading_model"))
    model = WhisperModel(
        get_assistant_environment("WAKE_MODEL", "tiny"),
        device="cpu",
        compute_type="int8",
    )
    recognizer = Recognizer(model)
    log.info(tr("wake.listening", phrase=f"Hola {get_assistant_name()}"))
    pending_request = False
    pending_id = None
    pending_launch = False

    while True:
        try:
            if inbox is None:
                inbox = WakeInbox()
            if pending_request:
                inbox.enqueue(WAKE_RECORD_REQUEST, command_id=pending_id,
                              ttl=settings.delivery_seconds)
                log.info("Wake recording request queued: %s", pending_id)
                pending_request = False
            if pending_launch:
                pending_launch = False
                try:
                    launch_assistant()
                except OSError:
                    log.exception("Unable to launch Arlo")
            if audio_requested() or not microphone.acquire():
                time.sleep(0.1)
                continue
            try:
                if not audio_requested():
                    activated = capture_wake_word(recognizer, settings)
                    if activated:
                        pending_request = True
                        pending_id = uuid.uuid4().hex
                        pending_launch = not is_assistant_running()
            finally:
                microphone.release()
        except Exception:
            log.exception("Wake interaction failed; retrying")
            time.sleep(1)


if __name__ == "__main__":
    # noinspection PyBroadException
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception:
        log.exception(tr("wake.detector_error"))
        sys.exit(1)
