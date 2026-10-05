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
import io
import json
import logging
import os
import sys
import threading
import time
import wave
from array import array
from collections import deque
from math import gcd

from .colors import RESET_COLOR, USER_COLOR
from .lang import tr

VOICE_MODEL_NAME = os.environ.get("WHISPER_MODEL", "small")
VOICE_BLOCK_SECONDS = 0.1
VOICE_MAX_SECONDS = 30
VOICE_START_TIMEOUT_SECONDS = 10
VOICE_END_SILENCE_SECONDS = 1.8
VOICE_SILENCE_THRESHOLD = 400
PLAYBACK_SILENCE_THRESHOLD = 900
ECHO_TAIL_SECONDS = 1.5
ECHO_FLOOR_BLOCKS = 40
ECHO_FLOOR_FACTOR = 2.5
PARTIAL_SILENCE_SECONDS = 0.5
BARGE_IN_SECONDS = 0.6
BARGE_IN_GAP_SECONDS = 0.4
_VOICE_MODEL = None
_VOICE_MODEL_LOCK = threading.Lock()


class LiveVoiceCapture:
    def __init__(self, sample_rate, *, silence_seconds=1.2, idle_seconds=30,
                 partial_seconds=PARTIAL_SILENCE_SECONDS):
        import numpy as np
        from scipy.signal import correlate, resample_poly

        self.correlate = correlate
        self.resample = resample_poly
        self.sample_rate = sample_rate
        self.silence_seconds = silence_seconds
        self.idle_seconds = idle_seconds
        self.partial_seconds = partial_seconds
        self.paused = False
        self.reference = np.empty(0, dtype=np.float32)
        self.reference_time = 0.0
        self.reference_lock = threading.Lock()
        self.pre_roll = deque(maxlen=4)
        self.echo_levels = deque(maxlen=ECHO_FLOOR_BLOCKS)
        self.frames = []
        self.started = False
        self.speech_seconds = 0.0
        self.silent_seconds = 0.0
        self.idle = 0.0
        self.event = None

    def playback(self, samples, sample_rate):
        import numpy as np

        samples = np.asarray(samples, dtype=np.float32).reshape(-1)
        if sample_rate != self.sample_rate:
            divisor = gcd(sample_rate, self.sample_rate)
            samples = self.resample(samples, self.sample_rate // divisor,
                                    sample_rate // divisor)
        with self.reference_lock:
            now = time.monotonic()
            if now - self.reference_time > ECHO_TAIL_SECONDS:
                self.reference = self.reference[:0]
            self.reference = np.concatenate((self.reference, samples))[
                -int(self.sample_rate * ECHO_TAIL_SECONDS):]
            self.reference_time = now

    def suppress_echo(self, samples):
        import numpy as np

        with self.reference_lock:
            recent = time.monotonic() - self.reference_time < ECHO_TAIL_SECONDS
            reference = self.reference.copy() if recent else self.reference[:0]
        if len(reference) < len(samples):
            return samples, recent
        probe = samples.astype(np.float64)
        source = reference.astype(np.float64)
        correlation = self.correlate(source, probe, mode="valid", method="fft")
        energy = np.concatenate(([0.0], np.cumsum(source * source)))
        windows = energy[len(probe):] - energy[:-len(probe)]
        scores = np.abs(correlation) / np.sqrt(
            np.maximum(windows * np.dot(probe, probe), 1e-12))
        offset = int(np.argmax(scores))
        if scores[offset] < 0.35:
            return samples, recent
        echo = reference[offset:offset + len(samples)]
        if len(echo) != len(samples):
            return samples, recent
        gain = np.clip(np.dot(samples, echo) / max(np.dot(echo, echo), 1e-9), -3, 3)
        return samples - gain * echo, recent

    def speech_threshold(self, level, playback):
        if not playback:
            self.echo_levels.clear()
            return VOICE_SILENCE_THRESHOLD
        import numpy as np

        self.echo_levels.append(level)
        floor = float(np.median(self.echo_levels))
        return min(PLAYBACK_SILENCE_THRESHOLD,
                   max(VOICE_SILENCE_THRESHOLD, ECHO_FLOOR_FACTOR * floor))

    def snapshot(self):
        return b"".join(self.frames)

    def feed(self, pcm_data):
        import numpy as np

        self.event = None
        samples = np.frombuffer(pcm_data, dtype="<i2").astype(np.float32) / 32768.0
        samples, playback = self.suppress_echo(samples)
        pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
        duration = len(samples) / self.sample_rate
        level = pcm_rms(pcm)
        speech = level >= self.speech_threshold(level, playback)
        if not self.frames:
            self.idle = 0.0 if playback else self.idle + duration
            if not speech:
                self.pre_roll.append(pcm)
                if self.idle >= self.idle_seconds:
                    self.event = "timeout"
                return None
            self.frames.extend(self.pre_roll)
            self.pre_roll.clear()
        self.frames.append(pcm)
        self.silent_seconds = 0.0 if speech else self.silent_seconds + duration
        if speech:
            self.speech_seconds += duration
        elif not (playback and not self.started
                  and self.silent_seconds <= BARGE_IN_GAP_SECONDS):
            self.speech_seconds = 0.0
        if not self.started and self.speech_seconds >= (
                BARGE_IN_SECONDS if playback else 0.15):
            self.started = True
            self.event = "started"
        if self.started and self.event is None:
            if speech and self.paused:
                self.paused = False
                self.event = "resumed"
            elif (not speech and not self.paused
                    and self.silent_seconds >= self.partial_seconds):
                self.paused = True
                self.event = "pause"
        if (self.silent_seconds >= self.silence_seconds or
                sum(map(len, self.frames)) >= self.sample_rate * 2 * VOICE_MAX_SECONDS):
            recording = b"".join(self.frames) if self.started else None
            self.frames.clear()
            self.started = False
            self.paused = False
            self.speech_seconds = self.silent_seconds = self.idle = 0.0
            if recording is not None:
                self.event = "utterance"
            return recording
        return None


def pcm_rms(pcm_data: bytes) -> float:
    """Calculate the RMS volume of mono 16-bit PCM audio."""
    samples = array("h")
    samples.frombytes(pcm_data)
    if sys.byteorder == "big":
        samples.byteswap()
    if not samples:
        return 0.0
    return (sum(sample * sample for sample in samples) / len(samples)) ** 0.5


def record_voice(*, on_audio=None, stop_event=None,
                 stop_on_silence=True) -> tuple[bytes, int] | None:
    """Record speech and optionally finish automatically after end silence."""
    try:
        import sounddevice as sound
    except ImportError as error:
        raise RuntimeError(
            tr("voice.input_missing")
        ) from error

    device = sound.query_devices(kind="input")
    if int(device.get("max_input_channels", 0)) < 1:
        raise RuntimeError(tr("voice.no_microphone"))

    sample_rate = int(device.get("default_samplerate") or 16000)
    block_size = max(1, int(sample_rate * VOICE_BLOCK_SECONDS))
    maximum_blocks = int(VOICE_MAX_SECONDS / VOICE_BLOCK_SECONDS)
    start_timeout_blocks = int(
        VOICE_START_TIMEOUT_SECONDS / VOICE_BLOCK_SECONDS)
    silence_blocks_to_stop = int(
        VOICE_END_SILENCE_SECONDS / VOICE_BLOCK_SECONDS)

    audio_blocks: list[bytes] = []
    pre_roll: deque[bytes] = deque(maxlen=3)
    speech_started = False
    silent_blocks = 0

    with sound.RawInputStream(
            samplerate=sample_rate,
            blocksize=block_size,
            device=device["index"],
            channels=1,
            dtype="int16") as stream:
        for block_index in range(maximum_blocks):
            if stop_event is not None and stop_event.is_set():
                break
            data, _ = stream.read(block_size)
            audio_block = bytes(data)
            if on_audio is not None:
                on_audio(audio_block, sample_rate)
            contains_speech = pcm_rms(audio_block) >= VOICE_SILENCE_THRESHOLD

            if not speech_started:
                if contains_speech:
                    speech_started = True
                    audio_blocks.extend(pre_roll)
                    audio_blocks.append(audio_block)
                else:
                    pre_roll.append(audio_block)
                    if block_index >= start_timeout_blocks:
                        return None
                continue

            audio_blocks.append(audio_block)
            silent_blocks = 0 if contains_speech else silent_blocks + 1
            if stop_on_silence and silent_blocks >= silence_blocks_to_stop:
                break

    if not speech_started:
        return None
    return b"".join(audio_blocks), sample_rate


def get_voice_model():
    """Load the local multilingual speech model once, on first voice command."""
    global _VOICE_MODEL
    with _VOICE_MODEL_LOCK:
        if _VOICE_MODEL is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as error:
                raise RuntimeError(
                    tr("voice.recognition_missing")
                ) from error
            _VOICE_MODEL = WhisperModel(
                VOICE_MODEL_NAME, device="cpu", compute_type="int8",
                cpu_threads=os.cpu_count() or 4)
        return _VOICE_MODEL


def transcribe_voice(pcm_data: bytes, sample_rate: int, *, model=None,
                     language=None, beam_size=5, vad_filter=True) -> tuple[str, str]:
    """Transcribe PCM audio locally and return its text and detected language."""
    audio_file = io.BytesIO()
    with wave.open(audio_file, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)
    audio_file.seek(0)

    segments, information = (model if model is not None else get_voice_model()).transcribe(
        audio_file,
        language=language,
        task="transcribe",
        beam_size=beam_size,
        vad_filter=vad_filter,
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=False,
    )
    transcript = " ".join(
        segment.text.strip() for segment in segments if segment.text.strip()
    ).strip()
    return transcript, information.language


def recording_to_wav(pcm_data: bytes, sample_rate: int) -> bytes:
    """Convert captured mono PCM to Gemma's 16 kHz WAV input format."""
    import numpy as np
    from scipy.signal import resample_poly

    samples = np.frombuffer(pcm_data, dtype="<i2").astype(np.float32)
    samples /= 32768.0
    if sample_rate != 16000:
        divisor = gcd(sample_rate, 16000)
        samples = resample_poly(
            samples, 16000 // divisor, sample_rate // divisor)
    samples = np.clip(samples, -1.0, 1.0)

    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes((samples * 32767).astype("<i2").tobytes())

    return wav_buffer.getvalue()


class PartialTranscript:
    """Transcribes the speech heard so far in the background while the user pauses."""

    def __init__(self, pcm_data: bytes, sample_rate: int):
        self.text = ""
        self.done = threading.Event()
        self.started = time.monotonic()
        threading.Thread(target=self._run, args=(pcm_data, sample_rate),
                         name="assistant-voice-partial", daemon=True).start()

    def _run(self, pcm_data, sample_rate):
        log = logging.getLogger("assistant.latency")
        try:
            with wave.open(io.BytesIO(recording_to_wav(pcm_data, sample_rate)),
                           "rb") as wav:
                text, _ = transcribe_voice(
                    wav.readframes(wav.getnframes()), wav.getframerate(),
                    beam_size=1, vad_filter=False)
            self.text = text.strip()
            log.info("Voice latency: partial transcript ready %d ms after the pause began",
                     (time.monotonic() - self.started) * 1000)
        except Exception:
            logging.getLogger("assistant.voice").exception(
                "Partial transcription failed")
        finally:
            self.done.set()

    def wait(self, cancel_event=None) -> str:
        while not self.done.wait(0.05):
            if cancel_event is not None and cancel_event.is_set():
                return ""
        return self.text
