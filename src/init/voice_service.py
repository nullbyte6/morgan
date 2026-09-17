from __future__ import annotations

import queue
import re
import tempfile
import threading
import wave
import winsound
from pathlib import Path

from piper import PiperVoice

"""The class in charge of Nora's voice, using the piper lib
from pip"""
class VoiceService:
    def __init__(self, model_path: str | Path):
        self.model_path = Path(model_path)
        if not self.model_path.exists():
            raise FileNotFoundError(
                f"Piper voice model not found: {self.model_path}")

        self.voice = PiperVoice.load(str(self.model_path))
        self._queue: queue.Queue[str] = queue.Queue()
        self._worker = threading.Thread(
            target=self._voice_worker,
            daemon=True)

        self._worker.start()

    @staticmethod
    def _clean_text(text: str) -> str:
        """Remove formatting that should not be spoken."""
        text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
        text = re.sub(r"\*(.*?)\*", r"\1", text)
        text = re.sub(r"__(.*?)__", r"\1", text)
        text = re.sub(r"_(.*?)_", r"\1", text)
        text = re.sub(r"`([^`]+)`", r"\1", text)
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def say(self, text: str) -> None:
        """Queue text to be spoken."""
        text = self._clean_text(text)
        if text:
            self._queue.put(text)

    def _voice_worker(self) -> None:
        """Continuously consume queued sentences."""
        while True:
            text = self._queue.get()
            try:
                self._speak(text)
            finally:
                self._queue.task_done()

    def _speak(self, text: str) -> None:
        with tempfile.NamedTemporaryFile(
            suffix=".wav", delete=False) as tmp:
            path = Path(tmp.name)

        try:
            with wave.open(str(path), "wb") as wav_file:
                self.voice.synthesize_wav(text, wav_file)

            winsound.PlaySound(str(path), winsound.SND_FILENAME)
        finally:
            path.unlink(missing_ok=True)