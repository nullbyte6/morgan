from __future__ import annotations

import json
import socket
import threading

import numpy as np


# noinspection PyBroadException
class VoiceClient:
    """Client for Arlo's persistent TTS service."""

    def __init__(self, audio_callback=None, host: str = "127.0.0.1",
            port: int = 18765):
        self.audio_callback = audio_callback
        self._socket = socket.create_connection(
            (host, port), timeout=10)
        self._socket.settimeout(None)
        self._reader = self._socket.makefile(
            "r", encoding="utf-8")

        self._send_lock = threading.Lock()
        self._done = threading.Event()
        self._done.set()

        self._error = None
        self._closed = False

        self._thread = threading.Thread(
            target=self._listen,
            name="arlo-voice-client",
            daemon=True)
        self._thread.start()
        self._send({"type": "hello"})

    def _send(self, message: dict) -> None:
        data = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        with self._send_lock:
            if self._closed:
                raise RuntimeError("TTS connection is closed")
            try:
                self._socket.sendall(data)
            except OSError as error:
                self._error = error
                self._done.set()
                raise RuntimeError(
                    "Connection to TTS service lost") from error

    def _listen(self) -> None:
        try:
            for line in self._reader:
                message = json.loads(line)
                kind = message.get("type")

                if kind == "audio":
                    if self.audio_callback is not None:
                        try:
                            samples = np.asarray(
                                message["samples"],
                                dtype=np.float32)
                            self.audio_callback(
                                samples,
                                message["sample_rate"])
                        except Exception:
                            pass

                elif kind == "done":
                    self._done.set()

                elif kind == "error":
                    self._error = RuntimeError(
                        message.get("message", "TTS error"))
                    self._done.set()

        except (OSError, ValueError) as error:
            self._error = error

        finally:
            self._closed = True
            self._done.set()

    def enqueue(self, text: str) -> None:
        if not text or not text.strip():
            return

        self._error = None
        self._done.clear()
        self._send({"type": "enqueue", "text": text})

    def wait_until_done(self) -> None:
        self._send({"type": "wait"})
        self._done.wait()

        if self._error is not None:
            raise RuntimeError(
                f"TTS service failed: {self._error}") from self._error

    def close(self) -> None:
        if self._closed:
            return

        self._closed = True

        try:
            self._socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

        self._socket.close()
        self._done.set()
