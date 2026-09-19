from __future__ import annotations

import json
import logging
import socket
import threading

import numpy as np

from .brain import (
    VOICE_MODEL,
    VOICE_REFERENCE,
    VOICE_REFERENCE_TEXT)

from .voice_service import VoiceService


HOST = "127.0.0.1"
PORT = 18765

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("arlo.tts.server")


class TTSServer:

    def __init__(self):
        self._client = None
        self._client_lock = threading.Lock()
        self._send_lock = threading.Lock()
        logger.info("Loading CosyVoice...")

        self.voice = VoiceService(
            model_path=VOICE_MODEL,
            voice_reference=VOICE_REFERENCE,
            reference_text=VOICE_REFERENCE_TEXT,
            speed=1.0,
            audio_callback=self._on_audio,
            speaking_callback=self._on_speaking)
        logger.info("CosyVoice ready")

    def _send(self, message: dict, client=None) -> None:
        data = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        with self._send_lock:
            with self._client_lock:
                if client is None:
                    client = self._client

            if client is None:
                return

            try:
                client.sendall(data)
            except OSError:
                logger.warning("Client disconnected")

    def _on_speaking(self, speaking, turn_id):
        self._send({"type": "speaking", "speaking": speaking, "turn_id": turn_id})

    def _on_audio(self, samples, sample_rate, turn_id) -> None:
        with self._client_lock:
            if self._client is None:
                return

        samples = np.asarray(samples, dtype=np.float32).reshape(-1)
        if samples.size == 0:
            return

        indices = np.linspace(
            0,
            samples.size - 1,
            min(128, samples.size),
            dtype=int)

        self._send({
            "type": "audio",
            "turn_id": turn_id,
            "samples": samples[indices].tolist(),
            "sample_rate": sample_rate,
        })

    def _wait_for_audio(self, client, turn_id, batch) -> None:
        try:
            if batch.turn_id == turn_id:
                self.voice.wait_until_done(batch)
            self._send({"type": "done", "turn_id": turn_id}, client)
        except Exception as error:
            logger.exception("TTS wait failed")
            self._send({
                "type": "error",
                "turn_id": turn_id,
                "message": str(error),
            }, client)

    def _handle_client(self, client: socket.socket) -> None:
        with self._client_lock:
            self._client = client

        logger.info("Arlo connected")

        try:
            with client.makefile(
                "r", encoding="utf-8") as reader:

                for line in reader:
                    message = json.loads(line)
                    kind = message.get("type")
                    if kind == "hello":
                        logger.info("Voice client ready")
                        self._send({"type": "hello", "interruptible": True}, client)

                    elif kind == "enqueue":
                        text = message.get("text", "")
                        if text.strip():
                            self.voice.enqueue(text, message.get("turn_id"))

                    elif kind == "stop":
                        self.voice.stop(message.get("turn_id"))

                    elif kind == "wait":
                        threading.Thread(
                            target=self._wait_for_audio,
                            args=(client, message.get("turn_id"), self.voice.current_batch()),
                            name="arlo-tts-wait",
                            daemon=True,
                        ).start()

                    else:
                        logger.warning("Unknown message: %s", kind)

        except (OSError, ValueError) as error:
            logger.warning("Client error: %s", error)

        finally:
            with self._client_lock:
                if self._client is client:
                    self._client = None

            client.close()
            logger.info("Arlo disconnected")
            self.voice.stop()

    def run(self) -> None:
        with socket.socket(
            socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_REUSEADDR,
                1)

            server.bind((HOST, PORT))
            server.listen(1)

            logger.info("TTS listening on %s:%s", HOST, PORT)
            while True:
                client, address = server.accept()
                self._handle_client(client)


def main():
    server = TTSServer()

    try:
        server.run()
    except KeyboardInterrupt:
        logger.info("Stopping TTS service")


if __name__ == "__main__":
    main()
