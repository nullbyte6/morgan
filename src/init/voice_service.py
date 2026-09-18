from __future__ import annotations

import logging
import queue
import sys
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
        if text:
            self._speech_done.clear()
            self._text_queue.put(text)

    def _tts_loop(self) -> None:
        """Generates audio from text to speech and adds it to the queue"""
        while True:
            text = self._text_queue.get()
            try:
                self.speaking = True
                generator = self.voice.inference_zero_shot(
                    text,
                    self.reference_text,
                    str(self.voice_reference),
                    zero_shot_spk_id="arlo",
                    stream=True,
                    speed=self.speed
                )
                for chunk in generator:
                    audio = chunk["tts_speech"]
                    if hasattr(audio, "detach"):
                        audio = audio.detach().cpu().numpy()
                    samples = np.asarray(audio, dtype=np.float32).squeeze()
                    if samples.size:
                        self._audio_queue.put(samples)
            except Exception as e:
                logging.error(f"Error en inferencia de voz: {e}")
            finally:
                self._text_queue.task_done()

    def _play_loop(self) -> None:
        frame_size = int(self.sample_rate * 0.04)

        with sd.OutputStream(samplerate=self.sample_rate, channels=1,
                             dtype="float32") as stream:
            while True:
                samples = self._audio_queue.get()
                try:
                    for start in range(0, len(samples), frame_size):
                        frame = samples[start:start + frame_size]

                        if self.audio_callback is not None:
                            self.audio_callback(frame, self.sample_rate)

                        stream.write(frame)
                finally:
                    self._audio_queue.task_done()

                if (self._text_queue.unfinished_tasks == 0 and
                        self._audio_queue.unfinished_tasks == 0):
                    self.speaking = False
                    self._speech_done.set()

    def wait_until_done(self) -> None:
        self._speech_done.wait()