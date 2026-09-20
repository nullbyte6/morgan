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

import ctypes
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

from src.init.lang import LANGUAGES, get_language, tr
from src.init.voice import transcribe_voice
from src.init.voice_ipc import ProcessLock, WakeInbox, audio_requested, voice_directory
from src.init.wake_capture import BLOCK_SECONDS, SAMPLE_RATE, WakeCapture, WakeSettings

ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "arlo.bat"

logging.basicConfig(
    level=logging.INFO,
    format="[Wake] %(message)s")

log = logging.getLogger("arlo.wake")

def is_arlo_running() -> bool:
    """Check whether an Arlo desktop instance is running."""
    if sys.platform != "win32":
        return False

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenMutexW.argtypes = [
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_wchar_p,
    ]
    kernel32.OpenMutexW.restype = ctypes.c_void_p

    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int

    SYNCHRONIZE = 0x00100000
    ERROR_ACCESS_DENIED = 5

    handle = kernel32.OpenMutexW(
        SYNCHRONIZE,
        False, r"Local\Diego.Arlo.Desktop",)

    if handle:
        kernel32.CloseHandle(handle)
        return True

    error = ctypes.get_last_error()
    if error == ERROR_ACCESS_DENIED:
        return True

    return False

def launch_arlo() -> None:
    if not LAUNCHER.is_file():
        log.error(tr("wake.launcher_not_found", path=LAUNCHER))
        return

    if is_arlo_running():
        log.info(tr("wake.already_running"))
        return

    log.info(tr("wake.activation_detected"))
    subprocess.Popen(
        ["cmd.exe", "/c", str(LAUNCHER)],
        cwd=str(ROOT),
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


class Launcher:
    """Throttle startup attempts while the existing services launcher runs."""

    def __init__(self):
        self.next_attempt = 0.0

    def ensure_running(self):
        if time.monotonic() < self.next_attempt:
            return
        self.next_attempt = time.monotonic() + 30
        try:
            launch_arlo()
        except OSError:
            log.exception("Unable to launch Arlo; pending commands remain in the inbox")


class Recognizer:
    """One model, one inference at a time; audio never waits for transcription."""

    def __init__(self, model):
        self.model = model
        self.future = None

    def available(self):
        return self.future is None or self.future.done()

    def submit(self, snapshot):
        future = self.future = Future()

        def recognize():
            try:
                text, _ = transcribe_voice(
                    snapshot.pcm, SAMPLE_RATE, model=self.model,
                    language=None if snapshot.final else LANGUAGES[get_language()],
                    beam_size=5 if snapshot.final else 1,
                    vad_filter=snapshot.final)
                future.set_result(text)
            except Exception as error:
                future.set_exception(error)

        threading.Thread(target=recognize, name="wake-stt", daemon=True).start()
        return future


def capture_command(recognizer, settings, launcher, maintenance=lambda: None):
    """Called with the microphone lock held. Closing this scope closes input."""
    import sounddevice as sd

    frames = queue.Queue(maxsize=50)
    overflow = threading.Event()
    capture = WakeCapture(settings)
    job = None
    last_frame = time.monotonic()
    next_maintenance = last_frame

    def receive(data, count, timing, status):
        if status:
            overflow.set()
        try:
            frames.put_nowait(bytes(data))
        except queue.Full:
            overflow.set()

    with sd.RawInputStream(samplerate=SAMPLE_RATE,
                           blocksize=int(SAMPLE_RATE * BLOCK_SECONDS),
                           channels=1, dtype="int16", callback=receive):
        while not audio_requested():
            now = time.monotonic()
            if now >= next_maintenance:
                maintenance()
                next_maintenance = now + 1
            try:
                pcm = frames.get(timeout=0.2)
            except queue.Empty:
                if time.monotonic() - last_frame > 5:
                    raise TimeoutError("Microphone stopped providing audio")
                continue
            last_frame = time.monotonic()
            if overflow.is_set():
                raise RuntimeError("Audio input overflow; discarded incomplete interaction")
            capture.feed(pcm)
            if job is not None:
                snapshot, future, started = job
                if future.done():
                    command = capture.accept_transcript(snapshot, future.result())
                    job = None
                    if command:
                        # A priority request may have arrived during inference.
                        return None if audio_requested() else command
                elif time.monotonic() - started > settings.recognition_seconds:
                    raise TimeoutError("Wake transcription timed out")
            if capture.event == "activated":
                capture.event = None
                launcher.ensure_running()
            elif capture.event in ("timeout", "too_long"):
                log.info("Wake capture ended: %s", capture.event)
                capture = WakeCapture(settings)
            if job is None and recognizer.available():
                snapshot = capture.next_transcription()
                if snapshot is not None:
                    job = snapshot, recognizer.submit(snapshot), time.monotonic()
    return None


def main() -> None:
    # Scheduler and manual starts share the same crash-safe singleton lock.
    singleton = ProcessLock("wake-listener")
    if not singleton.acquire():
        return
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
    launcher = Launcher()
    log.info(tr("wake.loading_model"))
    model = WhisperModel(
        os.environ.get("ARLO_WAKE_MODEL", "tiny"),
        device="cpu",
        compute_type="int8",
    )
    recognizer = Recognizer(model)
    log.info(tr("wake.listening", phrase="Hola Arlo"))
    pending_command = None
    pending_id = None

    def maintain_delivery():
        if inbox.has_pending():
            launcher.ensure_running()

    while True:
        try:
            if inbox is None:
                inbox = WakeInbox()
            if pending_command is not None:
                # Retain the same ID across busy-database retries.
                inbox.enqueue(pending_command, command_id=pending_id,
                              ttl=settings.delivery_seconds)
                log.info("Wake command queued: %s", pending_id)
                pending_command = None
            maintain_delivery()
            if audio_requested() or not microphone.acquire():
                time.sleep(0.1)
                continue
            try:
                # Recheck after acquisition to close the handoff race.
                if not audio_requested():
                    pending_command = capture_command(recognizer, settings, launcher,
                                                      maintain_delivery)
                    if pending_command:
                        pending_id = uuid.uuid4().hex
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
