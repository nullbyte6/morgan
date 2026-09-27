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

from __future__ import annotations
from src.init.lang import tr
from .identity import get_assistant_identifier

import base64
import json
import logging
import socket
import threading
import time

import numpy as np

from .voice_profiles import (
    VOICE_MODEL,
    VOICE_REFERENCE,
    VOICE_REFERENCE_TEXT)

from .voice_service import VoiceService


HOST = "127.0.0.1"
PORT = 18765

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(f"{get_assistant_identifier()}.tts.server")


class TTSServer:

    def __init__(self):
        self._client = None
        self._client_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._playback_reference = False
        self._last_audio_update = 0.0
        logger.info(tr('tts_server.loading_cosyvoice'))

        self.voice = VoiceService(
            model_path=VOICE_MODEL,
            voice_reference=VOICE_REFERENCE,
            reference_text=VOICE_REFERENCE_TEXT,
            speed=1.0,
            audio_callback=self._on_audio,
            speaking_callback=self._on_speaking,
            subtitle_callback=self._on_subtitle)
        logger.info(tr('tts_server.cosyvoice_ready'))

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
                logger.warning(tr('tts_server.client_disconnected'))

    def _on_speaking(self, speaking, turn_id):
        self._send({"type": "speaking", "speaking": speaking, "turn_id": turn_id})

    def _on_subtitle(self, text, turn_id):
        self._send({"type": "subtitle", "text": text, "turn_id": turn_id})

    def _on_audio(self, samples, sample_rate, turn_id) -> None:
        with self._client_lock:
            if self._client is None:
                return
            reference = self._playback_reference

        now = time.monotonic()
        if not reference and now - self._last_audio_update < 0.10:
            return
        self._last_audio_update = now

        samples = np.asarray(samples, dtype=np.float32).reshape(-1)
        if samples.size == 0:
            return

        message = {
            "type": "audio",
            "turn_id": turn_id,
            "sample_rate": sample_rate,
        }
        if reference:
            pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
            message["pcm"] = base64.b64encode(pcm).decode("ascii")
        else:
            indices = np.linspace(0, samples.size - 1, min(128, samples.size), dtype=int)
            message["samples"] = samples[indices].tolist()
        self._send(message)

    def _wait_for_audio(self, client, turn_id, batch) -> None:
        try:
            if batch.turn_id == turn_id:
                self.voice.wait_until_done(batch)
            self._send({"type": "done", "turn_id": turn_id}, client)
        except Exception as error:
            logger.exception(tr('tts_server.tts_wait_failed'))
            self._send({
                "type": "error",
                "turn_id": turn_id,
                "message": str(error),
            }, client)

    def _handle_client(self, client: socket.socket) -> None:
        with self._client_lock:
            self._client = client
            self._playback_reference = False

        logger.info(tr('tts_server.assistant_connected'))

        try:
            with client.makefile(
                "r", encoding="utf-8") as reader:

                for line in reader:
                    message = json.loads(line)
                    kind = message.get("type")
                    if kind == "hello":
                        logger.info(tr('tts_server.voice_client_ready'))
                        self._send({"type": "hello", "interruptible": True,
                                    "voice_selection": True,
                                    "playback_reference": True}, client)

                    elif kind == "playback_reference":
                        with self._client_lock:
                            self._playback_reference = bool(message.get("enabled"))

                    elif kind == "enqueue":
                        text = message.get("text", "")
                        if text.strip():
                            try:
                                self.voice.enqueue(text, message.get("turn_id"),
                                                   message.get("voice_reference"),
                                                   message.get("language_context", ""))
                            except (OSError, ValueError) as error:
                                self._send({"type": "error", "message": str(error),
                                            "turn_id": message.get("turn_id")}, client)

                    elif kind == "stop":
                        self.voice.stop(message.get("turn_id"))

                    elif kind == "wait":
                        threading.Thread(
                            target=self._wait_for_audio,
                            args=(client, message.get("turn_id"), self.voice.current_batch()),
                            name=f"{get_assistant_identifier()}-tts-wait",
                            daemon=True,
                        ).start()

                    else:
                        logger.warning(tr('tts_server.unknown_message_s'), kind)

        except (OSError, ValueError) as error:
            logger.warning(tr('tts_server.client_error_s'), error)

        finally:
            with self._client_lock:
                if self._client is client:
                    self._client = None

            client.close()
            logger.info(tr('tts_server.assistant_disconnected'))
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

            logger.info(tr('tts_server.tts_listening_on_s_s'), HOST, PORT)
            while True:
                client, address = server.accept()
                self._handle_client(client)


def main():
    server = TTSServer()

    try:
        server.run()
    except KeyboardInterrupt:
        logger.info(tr('tts_server.stopping_tts_service'))


if __name__ == "__main__":
    main()
