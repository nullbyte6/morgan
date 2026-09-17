from __future__ import annotations

import logging
import queue
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
logging.getLogger("root").setLevel(logging.WARNING)
logging.getLogger().setLevel(logging.ERROR)
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

import cosyvoice.cli.cosyvoice as cosyvoice_module
from cosyvoice.cli.cosyvoice import AutoModel

def _silent_tqdm(iterable, *args, **kwargs):
    return iterable

cosyvoice_module.tqdm = _silent_tqdm

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

        self.voice = None
        self.sample_rate = None
        self._audio_stream = None

        self._ready = threading.Event()
        self._load_error = None

        self._response_queue: queue.Queue = queue.Queue()
        self._tts_worker = threading.Thread(
            target=self._tts_loop,
            daemon=True,
        )
        self._tts_worker.start()

        self._loader = threading.Thread(
            target=self._load_model,
            daemon=True,
        )
        self._loader.start()

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

    def _tts_loop(self) -> None:
        self._wait_until_ready()
        while True:
            response = self._response_queue.get()
            try:
                self._speak_response(response)
            except Exception as error:
                print(f"VOICE ERROR: {error}")
            finally:
                self._response_queue.task_done()

    def _load_model(self) -> None:
        try:
            self.voice = AutoModel(
                model_dir=str(self.model_path),
                fp16=True,
            )

            self.sample_rate = self.voice.sample_rate
            self.voice.add_zero_shot_spk(
                self.reference_text,
                str(self.voice_reference),
                "arlo",
            )

            self._audio_stream = sd.OutputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                blocksize=0,
                latency="low",
            )
            self._audio_stream.start()

        except Exception as error:
            self._load_error = error

        finally:
            self._ready.set()

    def start_response(self) -> queue.Queue:
        """
        Start one continuous CosyVoice bi-streaming response.
        """
        text_queue = queue.Queue()
        self._response_queue.put(text_queue)
        return text_queue

    def feed_response(self, response: queue.Queue, text: str) -> None:
        text = self._clean_text(text)
        if text:
            response.put(text)

    def end_response(self, response: queue.Queue) -> None:
        response.put(None)

    def _wait_until_ready(self) -> None:
        self._ready.wait()
        if self._load_error is not None:
            raise RuntimeError(
                f"CosyVoice failed to load: {self._load_error}"
            ) from self._load_error

    @staticmethod
    def _text_stream(text_queue: queue.Queue):
        while True:
            text = text_queue.get()
            try:
                if text is None:
                    return

                yield text
            finally:
                text_queue.task_done()

    def _speak_response(self, text_queue: queue.Queue) -> None:
        text_stream = self._text_stream(text_queue)

        generator = self.voice.inference_zero_shot(
            text_stream,
            self.reference_text,
            str(self.voice_reference),
            zero_shot_spk_id="arlo",
            stream=True,
            speed=self.speed,
        )

        for chunk in generator:
            audio = chunk["tts_speech"]
            if hasattr(audio, "detach"):
                audio = audio.detach().cpu().numpy()

            samples = np.asarray(audio, dtype=np.float32).squeeze()

            if samples.ndim == 1:
                samples = samples.reshape(-1, 1)

            self._audio_stream.write(samples)