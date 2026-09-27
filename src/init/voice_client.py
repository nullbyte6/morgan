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

import base64
import json
import socket
import threading
import time
import uuid

import numpy as np
from .lang import tr
from .identity import get_assistant_identifier
from .voice_profiles import selected_voice


# noinspection PyBroadException
class VoiceClient:
    """Client for Arlo's persistent TTS service."""
    def __init__(self, audio_callback=None, host: str = "127.0.0.1",
            port: int = 18765):
        self.audio_callback = audio_callback
        self.speaking_callback = None
        self.subtitle_callback = None
        self._playback_lock = threading.RLock()
        self._muted = False
        self._turn_id = uuid.uuid4().hex
        self._language_context = ""
        self.supports_interruptions = False
        self.supports_voice_selection = False
        self.supports_playback_reference = False
        self._hello = threading.Event()
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
        self._last_progress = time.monotonic()
        self._progress_timeout = 240.0

        self._thread = threading.Thread(
            target=self._listen,
            name=f"{get_assistant_identifier()}-voice-client",
            daemon=True)
        self._thread.start()
        self._send({"type": "hello"})
        if not self._hello.wait(10) or not self.supports_voice_selection:
            self.close()
            raise RuntimeError(tr("voice.selection_restart"))

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
                    self.supports_voice_selection = bool(message.get("voice_selection"))
                    self.supports_playback_reference = bool(message.get("playback_reference"))
                    self._hello.set()
                    continue
                if (message.get("turn_id") != self._turn_id and
                        (self.supports_interruptions or "turn_id" in message)):
                    continue

                self._last_progress = time.monotonic()

                if kind == "audio":
                    callback = self.audio_callback
                    if callback is not None:
                        try:
                            if "pcm" in message:
                                samples = np.frombuffer(base64.b64decode(message["pcm"]),
                                                        dtype="<i2").astype(np.float32) / 32768.0
                            else:
                                samples = np.asarray(message["samples"], dtype=np.float32)
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

                elif kind == "subtitle":
                    callback = self.subtitle_callback
                    if callback is not None:
                        try:
                            callback(str(message.get("text", "")))
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
            self._hello.set()
            self._done.set()
            self._reader.close()

    def set_muted(self, muted: bool) -> None:
        """Stop current speech and suppress new speech without cancelling text."""
        with self._playback_lock:
            self._muted = bool(muted)
            if self._muted:
                self.stop()

    def set_playback_reference(self, enabled: bool) -> None:
        self._send({"type": "playback_reference", "enabled": bool(enabled)})

    def begin_turn(self, language_context="") -> None:
        with self._playback_lock:
            self._begin_turn()
            self._language_context = language_context

    def _begin_turn(self) -> None:
        if self._closed:
            raise RuntimeError(tr("voice.disconnected"))
        self._turn_id = uuid.uuid4().hex
        self._error = None
        self._last_progress = time.monotonic()
        self._done.set()

    def stop(self) -> None:
        with self._playback_lock:
            self._stop()

    def _stop(self) -> None:
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
        with self._playback_lock:
            if self._muted:
                if text and text.strip() and self.subtitle_callback is not None:
                    self.subtitle_callback(text)
                return
            self._enqueue(text)

    def _enqueue(self, text: str) -> None:
        if not text or not text.strip():
            return

        # Do not erase an asynchronous synthesis error when another phrase arrives.
        if self._error is not None:
            self.is_done()
        if self._done.is_set():
            self._last_progress = time.monotonic()
        reference = selected_voice()
        if reference is None:
            raise RuntimeError("No WAV voice references available")
        self._done.clear()
        self._send({"type": "enqueue", "text": text, "turn_id": self._turn_id,
                    "voice_reference": reference.name,
                    "language_context": self._language_context})

    def request_done(self) -> None:
        with self._playback_lock:
            if self._muted:
                self._done.set()
                return
            self._request_done()

    def _request_done(self) -> None:
        if self._error is not None:
            self.is_done()
        if self._done.is_set():
            self._last_progress = time.monotonic()
        self._done.clear()
        self._send({"type": "wait", "turn_id": self._turn_id})

    def is_done(self) -> bool:
        if (not self._done.is_set() and self._error is None and
                time.monotonic() - self._last_progress > self._progress_timeout):
            self._error = RuntimeError(tr("voice.timeout"))
            self._done.set()
        if self._error is not None:
            raise RuntimeError(tr("voice.failed", error=self._error)) from self._error
        return self._done.is_set()

    def wait_until_done(self) -> None:
        self.request_done()
        while not self._done.wait(0.1):
            self.is_done()

        self.is_done()

    def close(self) -> None:
        self._closed = True

        try:
            self._socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

        self._socket.close()
        self._done.set()
