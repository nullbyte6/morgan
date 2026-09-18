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


class VoiceService:
    """
    Arlo's multilingual voice service using Fun-CosyVoice3.
    The model is loaded once and kept alive for the entire Arlo session.
    Speech synthesis runs on a background worker so it does not block
    text generation.
    """

    def __init__(self, model_path, voice_reference, reference_text,
                 speed=1.0,
                 audio_callback=None):
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

        self._tts_worker = threading.Thread(target=self._tts_loop, daemon=True)
        self._tts_worker.start()

        self._player_worker = threading.Thread(target=self._play_loop, daemon=True)
        self._player_worker.start()

        self._speech_done = threading.Event()
        self._speech_done.set()

        self.audio_callback = audio_callback

    def enqueue(self, text: str) -> None:
        text = _clean_for_speech(text)

        if text:
            logger.debug("Queued: %s", text)
            self._speech_done.clear()
            self._text_queue.put(text)

    def _tts_loop(self) -> None:
        """TTS and TTS worker thread."""
        while True:
            text = self._text_queue.get()
            try:
                self.speaking = True
                logger.debug("Synthesizing: %s", text)

                generator = self.voice.inference_zero_shot(
                    text,
                    "",
                    "",
                    zero_shot_spk_id="arlo",
                    stream=True,
                    speed=self.speed)

                first_chunk = True
                for chunk in generator:
                    audio = chunk["tts_speech"]

                    if first_chunk:
                        logger.debug("First audio chunk ready")
                        first_chunk = False

                    if hasattr(audio, "detach"):
                        audio = audio.detach().cpu().numpy()

                    samples = np.asarray(audio, dtype=np.float32).squeeze()

                    if samples.size:
                        self._audio_queue.put(samples)

            except Exception:
                logger.exception("TTS inference failed")

            finally:
                self._text_queue.task_done()

    def _play_loop(self) -> None:
        frame_size = int(self.sample_rate * 0.04)
        prebuffer_samples = int(self.sample_rate * 0.16)

        ui_interval = 0.10
        last_ui_update = 0.0

        with sd.OutputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                latency="low",
                blocksize=0) as stream:
            buffered = []
            buffered_size = 0
            playing = False

            while True:
                samples = self._audio_queue.get()

                try:
                    if not playing:
                        buffered.append(samples)
                        buffered_size += len(samples)

                        if buffered_size < prebuffer_samples:
                            continue

                        samples = np.concatenate(buffered)
                        buffered.clear()
                        buffered_size = 0
                        playing = True

                    for start in range(0, len(samples), frame_size):
                        frame = samples[start:start + frame_size]

                        now = time.monotonic()

                        if (self.audio_callback is not None
                                and now - last_ui_update >= ui_interval):
                            self.audio_callback(frame, self.sample_rate)
                            last_ui_update = now

                        stream.write(frame)

                finally:
                    self._audio_queue.task_done()

                if (self._text_queue.unfinished_tasks == 0
                        and self._audio_queue.unfinished_tasks == 0):
                    playing = False
                    buffered.clear()
                    buffered_size = 0

                    self.speaking = False
                    self._speech_done.set()

    def wait_until_done(self) -> None:
        self._speech_done.wait()