from __future__ import annotations

import queue
import re
import threading
from pathlib import Path
import sounddevice as sd
from piper import PiperVoice, SynthesisConfig

"""The class in charge of Arlo's voice, using the piper lib
from pip"""
class VoiceService:
    def __init__(self, model_path: str | Path,
            speed: float = 1.0):
        self.model_path = Path(model_path)

        if not self.model_path.exists():
            raise FileNotFoundError(
                f"Piper voice model not found: {self.model_path}")

        self.voice = PiperVoice.load(str(self.model_path))
        self.synthesis_config = SynthesisConfig(
            length_scale=1.0/speed)

        self._queue: queue.Queue[str] = queue.Queue()
        self._worker = threading.Thread(
            target=self._voice_worker,
            daemon=True)

        self._worker.start()

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
            text)

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
        """Synthesize and play Piper audio progressively."""
        stream = None
        try:
            for chunk in self.voice.synthesize(text,
                    syn_config=self.synthesis_config):
                if stream is None:
                    stream = sd.RawOutputStream(
                        samplerate=chunk.sample_rate,
                        channels=chunk.sample_channels,
                        dtype="int16",
                    )
                    stream.start()

                stream.write(chunk.audio_int16_bytes)
        finally:
            if stream is not None:
                stream.stop()
                stream.close()