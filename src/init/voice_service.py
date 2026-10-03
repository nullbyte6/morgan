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

import gc
import http.client
import json
import logging
import queue
import re
import threading
import time
import warnings
from pathlib import Path

import numpy as np
import sounddevice as sd
from src.init.lang import tr
from .config import load_config
from .omni_server import GATEWAY_HOST, GATEWAY_PORT
from .speech_text import SpeechNumbers, prepare_speech
from .subtitle_timing import StreamingWordTimeline
from .voice_profiles import selected_voice, resolve_voice

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)
from .identity import get_assistant_identifier
from src.platforms import current_platform

logger = logging.getLogger(f"{get_assistant_identifier()}.tts")

RESUME_LEAD_SECONDS = 1.5
RESUME_MAX_WAIT_SECONDS = 2.5
SAMPLE_RATE = 24000
RECEIVE_TIMEOUT_SECONDS = 180
READ_BYTES = 9600
PHRASE_MIN_CHARS = 120
PHRASE_MAX_CHARS = 320
SENTENCE_END = re.compile(r"(?<=[.!?。！？…;；:\n])\s*")


def _raise_priority(*, process: bool) -> None:
    try:
        current_platform().raise_priority(process)
    except Exception:
        logger.exception("Unable to raise the voice priority")


def device_info() -> dict:
    """The voice backend reported to the assistant: the omni runtime and its model."""
    return {"backend": "llama.cpp-omni", "name": "MiniCPM-o 4.5"}


def _split_phrases(text: str) -> list[str]:
    """Group sentences into phrases long enough to sound natural and short enough to stay faithful."""
    parts = [part.strip() for part in SENTENCE_END.split(text) if part.strip()]
    phrases, current = [], ""
    for part in parts:
        if current and len(current) + len(part) + 1 > PHRASE_MAX_CHARS:
            phrases.append(current)
            current = part
        else:
            current = f"{current} {part}".strip()
        if len(current) >= PHRASE_MIN_CHARS:
            phrases.append(current)
            current = ""
    if current:
        phrases.append(current)
    return phrases


def _clean_for_speech(text: str) -> str:
    """Remove Markdown/formatting that should not be spoken."""
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"!\[([^]]*)]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^]]+)]\([^)]+\)", r"\1", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*>\s?", "", text)
    text = re.sub(r"(?m)^\s*[-+*]\s+", "", text)
    text = re.sub(r"(?m)^\s*\d+[.)]\s+", "", text)
    text = re.sub(r"[*_~]+", "", text)
    text = re.sub(r"(?m)^\s*[-*_]{3,}\s*$", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


class SpeechBatch:
    """Lifetime and completion belong to one turn, including in-flight synthesis."""

    def __init__(self, turn_id, language_context=""):
        self.turn_id = turn_id
        self.numbers = SpeechNumbers(language_context)
        self.cancelled = threading.Event()
        self.done = threading.Event()
        self.done.set()
        self.pending = 0
        self.speaking = False
        self.played = False
        self.subtitle = ""
        self.error = None


class VoiceService:
    """
    Arlo's multilingual voice service on the local MiniCPM-o omni model.
    The omni server keeps the model loaded for the entire Arlo session.
    Speech synthesis runs on a background worker so it does not block
    text generation.
    """

    def __init__(self, voice_reference,
                 audio_callback=None, speaking_callback=None,
                 subtitle_callback=None):
        _raise_priority(process=True)
        self.voice_reference = selected_voice() or Path(voice_reference)
        self.sample_rate = SAMPLE_RATE

        self._text_queue = queue.Queue()
        self._audio_queue = queue.Queue(maxsize=4)
        self._buffered_samples = 0
        self._synthesizing = False

        self.speaking = False
        self.audio_callback = audio_callback
        self.speaking_callback = speaking_callback
        self.subtitle_callback = subtitle_callback
        self._state_lock = threading.RLock()
        self._batch = SpeechBatch(None)

        self._tts_worker = threading.Thread(target=self._tts_loop, daemon=True)
        self._tts_worker.start()
        self._player_worker = threading.Thread(target=self._play_loop, daemon=True)
        self._player_worker.start()

    def enqueue(self, text: str, turn_id=None, voice_reference=None,
                language_context="") -> None:
        subtitle = _clean_for_speech(text)
        if not any(char.isalnum() for char in subtitle):
            return

        reference = (resolve_voice(voice_reference) if voice_reference is not None
                     else selected_voice())
        if reference is None:
            raise ValueError("No WAV voice references available")

        with self._state_lock:
            if self._batch.turn_id != turn_id or self._batch.cancelled.is_set():
                self.stop()
                self._batch = SpeechBatch(turn_id, language_context)

            batch = self._batch
            batch.numbers.observe(subtitle)
            text = prepare_speech(subtitle, load_config().get("pronunciations", {}),
                                  batch.numbers.code)
            text = batch.numbers.normalize(text)
            batch.pending += 1
            batch.done.clear()
            self._text_queue.put((batch, text, subtitle, reference))

    def current_batch(self):
        with self._state_lock:
            return self._batch

    def _set_speaking(self, batch, speaking):
        if batch.speaking == speaking:
            return
        batch.speaking = speaking
        self.speaking = speaking
        if self.speaking_callback is not None:
            self.speaking_callback(speaking, batch.turn_id)

    def _set_subtitle(self, batch, text):
        if batch.subtitle == text:
            return
        batch.subtitle = text
        if self.subtitle_callback is not None:
            self.subtitle_callback(text, batch.turn_id)

    def stop(self, turn_id=None) -> None:
        with self._state_lock:
            batch = self._batch
            if turn_id is not None and batch.turn_id != turn_id:
                return
            batch.cancelled.set()
            self._set_speaking(batch, False)
            self._set_subtitle(batch, "")
            batch.done.set()

    def _complete(self, batch):
        with self._state_lock:
            batch.pending -= 1
            if batch.pending == 0:
                if batch is self._batch:
                    self._set_speaking(batch, False)
                    self._set_subtitle(batch, "")
                batch.done.set()

    def _speak(self, phrase, reference, cancelled):
        connection = http.client.HTTPConnection(
            GATEWAY_HOST, GATEWAY_PORT, timeout=RECEIVE_TIMEOUT_SECONDS)
        try:
            connection.request(
                "POST", "/v1/audio/speech",
                json.dumps({"input": phrase, "voice": reference.name, "response_format": "pcm"}),
                {"Content-Type": "application/json"})
            response = connection.getresponse()
            if response.status != 200:
                raise RuntimeError(response.read().decode("utf-8", "replace"))
            remainder = b""
            while not cancelled.is_set():
                data = response.read1(READ_BYTES)
                if not data:
                    break
                data = remainder + data
                usable = len(data) - len(data) % 2
                remainder = data[usable:]
                if usable:
                    yield np.frombuffer(data[:usable], dtype="<i2").astype(np.float32) / 32768
        finally:
            connection.close()

    def _synthesize(self, text, reference, cancelled):
        for phrase in _split_phrases(text):
            yield from self._speak(phrase, reference, cancelled)

    def _tts_loop(self) -> None:
        idle_trimmed = False
        while True:
            try:
                batch, text, subtitle, reference = self._text_queue.get(timeout=15)
            except queue.Empty:
                with self._state_lock:
                    if (not idle_trimmed and self._batch.pending == 0
                            and self._text_queue.empty() and self._audio_queue.empty()):
                        self._release_idle_memory()
                        idle_trimmed = True
                continue
            idle_trimmed = False
            self._synthesizing = True
            generator = None
            timeline = StreamingWordTimeline(subtitle, self.sample_rate)
            sample_offset = 0
            try:
                if batch.cancelled.is_set():
                    continue
                generator = self._synthesize(text, reference, batch.cancelled)
                for chunk in generator:
                    if batch.cancelled.is_set():
                        break
                    samples = np.asarray(chunk, dtype=np.float32).reshape(-1)
                    if not samples.size:
                        continue
                    while not batch.cancelled.is_set():
                        with self._state_lock:
                            if batch.cancelled.is_set():
                                break
                            try:
                                self._audio_queue.put_nowait(
                                    (batch, samples, timeline, sample_offset))
                            except queue.Full:
                                pass
                            else:
                                batch.pending += 1
                                self._buffered_samples += len(samples)
                                sample_offset += len(samples)
                                break
                        batch.cancelled.wait(0.05)
            except Exception as error:
                batch.error = error
                logger.exception(tr('voice_service.tts_inference_failed'))
            finally:
                timeline.finalize(sample_offset)
                try:
                    if generator is not None:
                        generator.close()
                    generator = chunk = samples = timeline = None
                except Exception as error:
                    batch.error = error
                    logger.exception(tr('voice_service.tts_generator_cleanup_failed'))
                finally:
                    self._synthesizing = False
                    self._text_queue.task_done()
                    self._complete(batch)
                    generator = chunk = samples = timeline = None

    def _release_idle_memory(self):
        try:
            gc.collect()
            current_platform().trim_memory()
            logger.info("Voice service released idle memory")
        except Exception:
            logger.exception("Unable to release idle voice memory")

    def _await_lead(self, batch) -> None:
        deadline = time.monotonic() + RESUME_MAX_WAIT_SECONDS
        while not batch.cancelled.is_set() and time.monotonic() < deadline:
            with self._state_lock:
                lead = self._buffered_samples / self.sample_rate
                busy = self._synthesizing or not self._text_queue.empty()
            if lead >= RESUME_LEAD_SECONDS or not busy:
                return
            batch.cancelled.wait(0.02)

    def _play_loop(self) -> None:
        _raise_priority(process=False)
        frame_size = max(1, int(self.sample_rate * 0.04))
        stream = None
        while True:
            try:
                item = self._audio_queue.get_nowait()
                starved = False
            except queue.Empty:
                item = self._audio_queue.get()
                starved = True
            batch, samples, timeline, sample_offset = item
            length = len(samples)
            try:
                if batch.cancelled.is_set():
                    continue
                if starved and batch.played:
                    self._await_lead(batch)
                if stream is None:
                    stream = sd.OutputStream(samplerate=self.sample_rate, channels=1,
                                             dtype="float32", latency="low", blocksize=0)
                if not stream.active:
                    stream.start()
                for start in range(0, len(samples), frame_size):
                    with self._state_lock:
                        if batch.cancelled.is_set():
                            stream.abort()
                            break
                        batch.played = True
                        self._set_speaking(batch, True)
                        self._set_subtitle(
                            batch, timeline.text_at(sample_offset + start))
                    frame = samples[start:start + frame_size]
                    stream.write(frame)
                    if not batch.cancelled.is_set() and self.audio_callback is not None:
                        self.audio_callback(frame, self.sample_rate, batch.turn_id)
               
                if batch.cancelled.is_set():
                    stream.abort()
            except Exception as error:
                batch.error = error
                logger.exception(tr('voice_service.audio_playback_failed'))
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
                    stream = None
            finally:
                self._audio_queue.task_done()
                with self._state_lock:
                    self._buffered_samples -= length
                self._complete(batch)
                samples = frame = timeline = None

    def wait_until_done(self, batch=None) -> None:
        batch = batch if batch is not None else self.current_batch()
        batch.done.wait()
        if batch.error is not None and not batch.cancelled.is_set():
            raise RuntimeError(str(batch.error)) from batch.error
