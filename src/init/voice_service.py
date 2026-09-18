from __future__ import annotations

import logging
import queue
import sys
import re
import threading
import warnings
from pathlib import Path

import numpy as np
import sounddevice as sd
import torch
from transformers.utils import logging as transformers_logging

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

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
    """Remove speech-irrelevant Markdown from a streaming text chunk."""
    text = text.replace("*", "")
    text = text.replace("_", "")
    text = text.replace("`", "")
    text = text.replace("#", "")
    text = text.replace("~", "")
    return text


class VoiceService:
    """
    Arlo's multilingual voice service using Fun-CosyVoice3.
    LLM text and synthesized audio are both streamed:
        LLM -> text chunks -> CosyVoice -> PCM chunks -> sounddevice
    """
    _END = object()

    def __init__(
        self,
        model_path,
        voice_reference,
        reference_text,
        speed=1.0,
        audio_callback=None):

        self.model_path = Path(model_path)
        self.voice_reference = Path(voice_reference)

        reference_text = reference_text.strip()
        if "<|endofprompt|>" not in reference_text:
            reference_text = (
                "You are a helpful assistant.<|endofprompt|>"
                + reference_text
            )

        self.reference_text = reference_text
        self.speed = speed
        self.audio_callback = audio_callback

        self.voice = AutoModel(
            model_dir=str(self.model_path),
            fp16=True)

        self.sample_rate = self.voice.sample_rate
        self.voice.add_zero_shot_spk(
            self.reference_text,
            str(self.voice_reference),
            "arlo")

        self._request_queue = queue.Queue()
        self._audio_queue = queue.Queue()
        self._current_text_queue = None
        self._stream_lock = threading.Lock()
        self.speaking = False
        self._speech_done = threading.Event()
        self._speech_done.set()

        self._tts_worker = threading.Thread(
            target=self._tts_loop,
            daemon=True)
        self._tts_worker.start()

        self._player_worker = threading.Thread(
            target=self._play_loop,
            daemon=True)
        self._player_worker.start()

    def begin(self) -> None:
        """Start a new streaming speech request."""
        with self._stream_lock:
            if self._current_text_queue is not None:
                raise RuntimeError(
                    "A speech stream is already active."
                )

            text_queue = queue.Queue()

            self._current_text_queue = text_queue
            self._speech_done.clear()
            self._request_queue.put(text_queue)

    def feed(self, text: str) -> None:
        """Feed another LLM text chunk into the active speech stream."""
        if not text:
            return

        with self._stream_lock:
            text_queue = self._current_text_queue

        if text_queue is None:
            raise RuntimeError(
                "VoiceService.feed() called without begin().")

        text_queue.put(text)

    def end(self) -> None:
        """Tell CosyVoice that the current LLM response has finished."""
        with self._stream_lock:
            text_queue = self._current_text_queue
            if text_queue is None:
                return

            self._current_text_queue = None
        text_queue.put(self._END)

    def _text_stream(self, text_queue):
        """
        Generator consumed directly by CosyVoice.
        It blocks only when CosyVoice asks for more text faster than the
        LLM is producing it.
        """
        while True:
            item = text_queue.get()
            try:
                if item is self._END:
                    return

                text = _clean_for_speech(item)
                if text:
                    yield text

            finally:
                text_queue.task_done()

    def _tts_loop(self) -> None:
        """Run one bi-streaming CosyVoice inference per Arlo response."""
        while True:
            text_queue = self._request_queue.get()

            try:
                self.speaking = True

                generator = self.voice.inference_zero_shot(
                    self._text_stream(text_queue),
                    self.reference_text,
                    str(self.voice_reference),
                    zero_shot_spk_id="arlo",
                    stream=True,
                    speed=self.speed)

                for chunk in generator:
                    audio = chunk["tts_speech"]

                    if hasattr(audio, "detach"):
                        audio = audio.detach().cpu().numpy()

                    samples = np.asarray(
                        audio,
                        dtype=np.float32).squeeze()

                    if samples.size:
                        self._audio_queue.put(samples)

            except Exception as error:
                logging.error(
                    "Error en inferencia de voz: %s",
                    error)

            finally:
                self._request_queue.task_done()
                self._audio_queue.put(self._END)

    def _play_loop(self) -> None:
        frame_size = int(self.sample_rate * 0.04)

        with sd.OutputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32") as stream:

            while True:
                samples = self._audio_queue.get()

                try:
                    if samples is self._END:
                        self.speaking = False
                        self._speech_done.set()
                        continue

                    for start in range(0, len(samples), frame_size):
                        frame = samples[start:start + frame_size]

                        if self.audio_callback is not None:
                            self.audio_callback(frame, self.sample_rate)

                        stream.write(frame)

                finally:
                    self._audio_queue.task_done()

    def wait_until_done(self) -> None:
        self._speech_done.wait()