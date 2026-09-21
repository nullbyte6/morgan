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
import io
import json
import os
import sys
import wave
from array import array
from collections import deque

from .colors import RESET_COLOR, USER_COLOR
from .lang import tr

VOICE_COMMANDS = {"/voice", "voice"}
VOICE_MODEL_NAME = os.environ.get("WHISPER_MODEL", "small")
VOICE_BLOCK_SECONDS = 0.1
VOICE_MAX_SECONDS = 30
VOICE_START_TIMEOUT_SECONDS = 10
VOICE_END_SILENCE_SECONDS = 1.2
VOICE_SILENCE_THRESHOLD = 400
_VOICE_MODEL = None


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
    if _VOICE_MODEL is None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as error:
            raise RuntimeError(
                tr("voice.recognition_missing")
            ) from error
        _VOICE_MODEL = WhisperModel(
            VOICE_MODEL_NAME, device="cpu", compute_type="int8")
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


def capture_voice_input() -> str | None:
    """Capture and transcribe a single spoken command from the default microphone."""
    print("[MIC]", flush=True)
    recording = record_voice()
    if recording is None:
        print(tr("voice.not_detected"))
        return None

    try:
        transcript, language = transcribe_voice(*recording)
    finally:
        pass

    if not transcript:
        print(tr("voice.not_transcribed"))
        return None
    print(f"{USER_COLOR}[VOICE:{language}] {transcript}{RESET_COLOR}")
    return json.dumps({
        "voice_language": language,
        "voice_text": transcript,
    }, ensure_ascii=False)
