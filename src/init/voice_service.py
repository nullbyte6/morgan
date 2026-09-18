from __future__ import annotations

import logging
import re
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

import tqdm

_original_tqdm = tqdm.tqdm


def _quiet_tqdm(*args, **kwargs):
    kwargs["disable"] = True
    return _original_tqdm(*args, **kwargs)


tqdm.tqdm = _quiet_tqdm

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

    def __init__(self, model_path: str | Path,
                 voice_reference: str | Path, reference_text: str,
                 speed: float = 1.0):
        self.model_path = Path(model_path)
        self.voice_reference = Path(voice_reference)
        reference_text = reference_text.strip()
        if "<|endofprompt|>" not in reference_text:
            reference_text = ("You are a helpful assistant.<|endofprompt|>" +
                              reference_text)

        self.reference_text = reference_text
        self.speed = speed

        if not self.model_path.exists():
            raise FileNotFoundError(
                f"CosyVoice model not found: {self.model_path}"
            )

        if not self.voice_reference.exists():
            raise FileNotFoundError(
                f"Voice reference not found: {self.voice_reference}"
            )

        self.speaking = False
        self.voice = None
        self.sample_rate = None

        self._ready = threading.Event()
        self._load_error = None
        self._tts_error = None

        self._loader = threading.Thread(
            target=self._load_model,
            daemon=True,
        )
        self._loader.start()

    @property
    def error(self):
        return self._tts_error or self._load_error

    @staticmethod
    def _clean_text(text: str) -> str:
        """Remove formatting and symbols that should not be spoken."""

        text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
        text = re.sub(r"\*(.*?)\*", r"\1", text)
        text = re.sub(r"__(.*?)__", r"\1", text)
        text = re.sub(r"_(.*?)_", r"\1", text)
        text = re.sub(r"`([^`]+)`", r"\1", text)
        text = re.sub(r"https?://\S+", "", text)

        text = re.sub(
            "["
            "\U0001F1E0-\U0001F1FF"
            "\U0001F300-\U0001F5FF"
            "\U0001F600-\U0001F64F"
            "\U0001F680-\U0001F6FF"
            "\U0001F700-\U0001F77F"
            "\U0001F780-\U0001F7FF"
            "\U0001F800-\U0001F8FF"
            "\U0001F900-\U0001F9FF"
            "\U0001FA00-\U0001FAFF"
            "\U00002600-\U000026FF"
            "\U00002700-\U000027BF"
            "\U0000FE0F"
            "\U0000200D"
            "]+",
            "",
            text,
        )

        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _load_model(self) -> None:
        try:
            self.voice = AutoModel(
                model_dir=str(self.model_path),
                fp16=True)

            self.sample_rate = self.voice.sample_rate

            self.voice.add_zero_shot_spk(self.reference_text,
                                         str(self.voice_reference), "arlo")

        except Exception as error:
            self._load_error = error

        finally:
            self._ready.set()

    def speak(self, text: str) -> None:
        text = self._clean_text(text)
        if not text:
            return

        self._wait_until_ready()
        self.speaking = True

        try:
            generator = self.voice.inference_zero_shot(
                text,
                self.reference_text,
                str(self.voice_reference),
                zero_shot_spk_id="arlo",
                stream=False,
                speed=self.speed)

            audio_parts = []

            for chunk in generator:
                audio = chunk["tts_speech"]

                if hasattr(audio, "detach"):
                    audio = audio.detach().cpu().numpy()

                samples = np.asarray(audio, dtype=np.float32).squeeze()
                if samples.size:
                    audio_parts.append(samples)

            if audio_parts:
                audio = np.concatenate(audio_parts)
                sd.play(audio, samplerate=self.sample_rate)
                sd.wait()
        finally:
            self.speaking = False