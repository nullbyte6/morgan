from __future__ import annotations

import logging
import queue
import sys
import re
import threading
import warnings
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import torch
from transformers.utils import logging as transformers_logging

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)
logger = logging.getLogger("arlo.tts")

def _silence_tts_loggers():
    prefixes = (
        "cosyvoice",
        "modelscope",
        "onnxruntime",
        "transformers",
        "ttsfrd",
        "wetext",
    )

    for name in prefixes:
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = False
        logger.disabled = True

transformers_logging.set_verbosity_error()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
MATCHA_DIR = SRC_DIR / "third_party" / "Matcha-TTS"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

if str(MATCHA_DIR) not in sys.path:
    sys.path.insert(0, str(MATCHA_DIR))

torch.backends.cuda.enable_flash_sdp(False)
torch.backends.cuda.enable_mem_efficient_sdp(False)
torch.backends.cuda.enable_math_sdp(True)

_silence_tts_loggers()
from cosyvoice.cli.cosyvoice import AutoModel
_silence_tts_loggers()

import shutil

if shutil.which("ffmpeg") is None:
    raise RuntimeError("FFmpeg is required by CosyVoice "
                       "but was not found in PATH.")


def _clean_for_speech(text: str) -> str:
    """Remove Markdown/formatting that should not be spoken."""
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"!\[([^\]]*)]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)]\([^)]+\)", r"\1", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*>\s?", "", text)
    text = re.sub(r"(?m)^\s*[-+*]\s+", "", text)
    text = re.sub(r"(?m)^\s*\d+[.)]\s+", "", text)
    text = re.sub(r"[*_~]+", "", text)
    text = re.sub(r"(?m)^\s*[-*_]{3,}\s*$", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


from decimal import Decimal, InvalidOperation
from num2words import num2words

SPANISH_NUMBER = re.compile(
    r"(?<![\w./\\])"
    r"-?(?:\d{1,3}(?:\.\d{3})+|\d+)"
    r"(?:,\d+)?"
    r"(?![\w./\\])"
)


def normalize_spanish_numbers(text: str) -> str:
    """Convert Spanish-formatted numbers to spoken Spanish."""
    def replace(match: re.Match) -> str:
        original = match.group()
        try:
            if "," in original:
                integer, fractional = original.split(",", 1)
                integer = integer.replace(".", "")
                whole = num2words(int(integer), lang="es")
                decimal_digits = " ".join(
                    num2words(int(digit), lang="es")
                    for digit in fractional)
                return f"{whole} coma {decimal_digits}"

            number = int(original.replace(".", ""))
            return num2words(number, lang="es")

        except (ValueError, InvalidOperation):
            return original

    return SPANISH_NUMBER.sub(replace, text)



class SpeechBatch:
    """Lifetime and completion belong to one turn, including in-flight synthesis."""

    def __init__(self, turn_id):
        self.turn_id = turn_id
        self.cancelled = threading.Event()
        self.done = threading.Event()
        self.done.set()
        self.pending = 0
        self.speaking = False
        self.error = None


class VoiceService:
    """
    Arlo's multilingual voice service using Fun-CosyVoice3.
    The model is loaded once and kept alive for the entire Arlo session.
    Speech synthesis runs on a background worker so it does not block
    text generation.
    """

    def __init__(self, model_path, voice_reference, reference_text,
                 speed=1.0,
                 audio_callback=None, speaking_callback=None):
        self.model_path = Path(model_path)
        self.voice_reference = Path(voice_reference)
        reference_text = reference_text.strip()
        if "<|endofprompt|>" not in reference_text:
            reference_text = "You are a helpful assistant.<|endofprompt|>" + reference_text

        self.reference_text = reference_text
        self.speed = speed

        self.voice = AutoModel(model_dir=str(self.model_path), fp16=True)
        self.sample_rate = self.voice.sample_rate
        self.voice.add_zero_shot_spk(self.reference_text, str(self.voice_reference), "arlo")

        self._text_queue = queue.Queue()
        self._audio_queue = queue.Queue()

        self.speaking = False
        self.audio_callback = audio_callback
        self.speaking_callback = speaking_callback
        self._state_lock = threading.RLock()
        self._batch = SpeechBatch(None)

        self._tts_worker = threading.Thread(target=self._tts_loop, daemon=True)
        self._tts_worker.start()
        self._player_worker = threading.Thread(target=self._play_loop, daemon=True)
        self._player_worker.start()

    def enqueue(self, text: str, turn_id=None) -> None:
        text = _clean_for_speech(text)
        text = normalize_spanish_numbers(text)
        with self._state_lock:
            if self._batch.turn_id != turn_id or self._batch.cancelled.is_set():
                self.stop()
                self._batch = SpeechBatch(turn_id)
            if text:
                batch = self._batch
                batch.pending += 1
                batch.done.clear()
                self._text_queue.put((batch, text))

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

    def stop(self, turn_id=None) -> None:
        with self._state_lock:
            batch = self._batch
            if turn_id is not None and batch.turn_id != turn_id:
                return
            batch.cancelled.set()
            self._set_speaking(batch, False)
            batch.done.set()

    def _complete(self, batch):
        with self._state_lock:
            batch.pending -= 1
            if batch.pending == 0:
                if batch is self._batch:
                    self._set_speaking(batch, False)
                batch.done.set()

    def _tts_loop(self) -> None:
        while True:
            batch, text = self._text_queue.get()
            generator = None
            try:
                if batch.cancelled.is_set():
                    continue
                generator = self.voice.inference_zero_shot(
                    text, "", "", zero_shot_spk_id="arlo", stream=True,
                    speed=self.speed)
                for chunk in generator:
                    if batch.cancelled.is_set():
                        # CosyVoice owns an internal token thread and releases its
                        # GPU caches only when this phrase's generator finishes.
                        # Drain it silently; queued phrases are skipped entirely.
                        continue
                    audio = chunk["tts_speech"]
                    if hasattr(audio, "detach"):
                        audio = audio.detach().cpu().numpy()
                    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
                    with self._state_lock:
                        if samples.size and not batch.cancelled.is_set():
                            batch.pending += 1
                            self._audio_queue.put((batch, samples))
            except Exception as error:
                batch.error = error
                logger.exception("TTS inference failed")
            finally:
                try:
                    if generator is not None:
                        generator.close()
                except Exception as error:
                    batch.error = error
                    logger.exception("TTS generator cleanup failed")
                finally:
                    self._text_queue.task_done()
                    self._complete(batch)

    def _play_loop(self) -> None:
        # Short writes bound interruption latency; every frame retains its turn.
        frame_size = max(1, int(self.sample_rate * 0.04))
        last_ui_update = 0.0
        stream = None
        while True:
            batch, samples = self._audio_queue.get()
            try:
                if batch.cancelled.is_set():
                    continue
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
                        self._set_speaking(batch, True)
                    frame = samples[start:start + frame_size]
                    stream.write(frame)
                    now = time.monotonic()
                    if (not batch.cancelled.is_set() and self.audio_callback is not None
                            and now - last_ui_update >= 0.10):
                        self.audio_callback(frame, self.sample_rate, batch.turn_id)
                        last_ui_update = now
                with self._state_lock:
                    drained = batch.pending == 1
                if batch.cancelled.is_set():
                    stream.abort()
                elif drained:
                    # Include device-buffer playback in the completion event.
                    stream.stop()
            except Exception as error:
                batch.error = error
                logger.exception("Audio playback failed")
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
                    stream = None
            finally:
                self._audio_queue.task_done()
                self._complete(batch)

    def wait_until_done(self, batch=None) -> None:
        batch = batch if batch is not None else self.current_batch()
        batch.done.wait()
        if batch.error is not None and not batch.cancelled.is_set():
            raise RuntimeError(str(batch.error)) from batch.error
