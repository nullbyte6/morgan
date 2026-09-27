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

from src.init.lang import LANGUAGES, get_language, tr
from src.init.voice import transcribe_voice
from src.init.voice_ipc import (
    WAKE_RECORD_REQUEST,
    ProcessLock,
    WakeInbox,
    audio_requested,
    voice_directory,
)
from src.init.identity import get_assistant_name, get_assistant_identifier
from src.init.wake_capture import BLOCK_SECONDS, SAMPLE_RATE, WakeCapture, WakeSettings

ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "scripts" / "arlo.bat"

logging.basicConfig(
    level=logging.INFO,
    format="[Wake] %(message)s")

log = logging.getLogger(f"{get_assistant_identifier()}.wake")


def prioritize_listener() -> None:
    """Keep foreground UI rendering from starving wake audio/inference."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel32.SetPriorityClass.restype = ctypes.c_int
        above_normal_priority_class = 0x00008000
        if not kernel32.SetPriorityClass(
                kernel32.GetCurrentProcess(), above_normal_priority_class):
            raise ctypes.WinError(ctypes.get_last_error())
    except OSError:
        log.exception("Unable to raise wake-listener priority")


def is_arlo_running() -> bool:
    """Check the lifetime lock without activating or launching the desktop."""
    lock = ProcessLock("desktop-running")
    if not lock.acquire():
        return True
    lock.release()
    return False


def launch_arlo() -> None:
    """Start the desktop without waiting for its services or UI."""
    if not LAUNCHER.is_file():
        log.error(tr("wake.launcher_not_found", path=LAUNCHER))
        return
    if is_arlo_running():
        return

    log.info(tr("wake.activation_detected"))
    subprocess.Popen(
        ["cmd.exe", "/c", str(LAUNCHER)],
        cwd=str(ROOT),
        creationflags=subprocess.CREATE_NO_WINDOW,
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
                    language=None if snapshot.final else LANGUAGES[get_language()],
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
    if sys.platform == "win32":
        # PortAudio's legacy MME default intermittently fails in a detached
        # pythonw process. Prefer the matching WASAPI endpoint when present.
        host_apis = sd.query_hostapis()
        for index, candidate in enumerate(sd.query_devices()):
            host_name = host_apis[candidate["hostapi"]]["name"]
            if (candidate["max_input_channels"] >= 1 and
                    candidate["name"] == device["name"] and
                    host_name == "Windows WASAPI"):
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
        os.environ.get("ARLO_WAKE_MODEL", "tiny"),
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
                # Retain the same ID across busy-database retries.
                inbox.enqueue(WAKE_RECORD_REQUEST, command_id=pending_id,
                              ttl=settings.delivery_seconds)
                log.info("Wake recording request queued: %s", pending_id)
                pending_request = False
            if pending_launch:
                # Each activation gets one launch attempt. A stale inbox entry
                # must never reopen a console or desktop every few seconds.
                pending_launch = False
                try:
                    launch_arlo()
                except OSError:
                    log.exception("Unable to launch Arlo")
            if audio_requested() or not microphone.acquire():
                time.sleep(0.1)
                continue
            try:
                # Recheck after acquisition to close the handoff race.
                if not audio_requested():
                    activated = capture_wake_word(recognizer, settings)
                    if activated:
                        pending_request = True
                        pending_id = uuid.uuid4().hex
                        pending_launch = not is_arlo_running()
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
