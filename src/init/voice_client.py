from __future__ import annotations

import json
import socket
import threading
import uuid

import numpy as np
from .lang import tr


# noinspection PyBroadException
class VoiceClient:
    """Client for Arlo's persistent TTS service."""
    def __init__(self, audio_callback=None, host: str = "127.0.0.1",
            port: int = 18765):
        self.audio_callback = audio_callback
        self.speaking_callback = None
        self._turn_id = uuid.uuid4().hex
        self.supports_interruptions = False
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
                raise RuntimeError(tr("voice.closed"))
            try:
                self._socket.sendall(data)
            except OSError as error:
                self._error = error
                self._done.set()
                raise RuntimeError(
                    tr("voice.disconnected")) from error

    def _listen(self) -> None:
        try:
            for line in self._reader:
                message = json.loads(line)
                kind = message.get("type")
                if kind == "hello":
                    self.supports_interruptions = bool(message.get("interruptible"))
                    continue
                if (message.get("turn_id") != self._turn_id and
                        (self.supports_interruptions or "turn_id" in message)):
                    continue

                if kind == "audio":
                    callback = self.audio_callback
                    if callback is not None:
                        try:
                            samples = np.asarray(
                                message["samples"],
                                dtype=np.float32)
                            callback(
                                samples,
                                message["sample_rate"])
                        except Exception:
                            pass

                elif kind == "speaking":
                    callback = self.speaking_callback
                    if callback is not None:
                        try:
                            callback(bool(message["speaking"]))
                        except Exception:
                            pass

                elif kind == "done":
                    self._done.set()

                elif kind == "error":
                    self._error = RuntimeError(
                        message.get("message", tr("voice.error")))
                    self._done.set()

        except (OSError, ValueError) as error:
            self._error = error

        finally:
            if not self._closed and self._error is None:
                self._error = RuntimeError(tr("voice.disconnected"))
            self._closed = True
            self._done.set()
            self._reader.close()

    def begin_turn(self) -> None:
        self._turn_id = uuid.uuid4().hex
        self._error = None
        self._done.set()

    def stop(self) -> None:
        if not self.supports_interruptions:
            if not self._done.is_set() and not self._closed:
                raise RuntimeError(tr("voice.restart"))
            return
        turn_id = self._turn_id
        self._turn_id = uuid.uuid4().hex
        self._done.set()
        if not self._closed:
            self._send({"type": "stop", "turn_id": turn_id})

    def enqueue(self, text: str) -> None:
        if not text or not text.strip():
            return

        self._error = None
        self._done.clear()
        self._send({"type": "enqueue", "text": text, "turn_id": self._turn_id})

    def request_done(self) -> None:
        self._done.clear()
        self._send({"type": "wait", "turn_id": self._turn_id})

    def is_done(self) -> bool:
        if self._error is not None:
            raise RuntimeError(tr("voice.failed", error=self._error)) from self._error
        return self._done.is_set()

    def wait_until_done(self) -> None:
        self.request_done()
        self._done.wait()

        self.is_done()

    def close(self) -> None:
        self._closed = True

        try:
            self._socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

        self._socket.close()
        self._done.set()
