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
import asyncio
import io
import logging
import threading
import time
import wave
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import *

from src.init.attachments import (DesktopMessage, DesktopVoiceMessage, AttachmentSession,
    ollama_capabilities)

from src.init.commands import set_confirmation_handler
from src.init.config import load_config
from src.init.core import Assistant
from src.init.lang import tr
from src.init.session_log import SessionLog
from src.init.voice_ipc import desktop_audio
from src.init.utils import spectrum_levels


class VoiceInputWorker(QThread):
    levels = Signal(object)
    processing = Signal()
    speech_started = Signal()
    utterance = Signal(object)

    def __init__(self, parent=None, *, automatic=False, live=False):
        super().__init__(parent)
        self.automatic = automatic
        self.live = live
        self.capture = None
        self.waiting_response = threading.Event()
        self.stop_event = threading.Event()
        self.audio_wav = b""
        self.transcript = ""
        self.error = ""

    def run(self):
        try:
            from src.init.voice import record_voice, recording_to_wav

            with desktop_audio(stop_event=self.stop_event, tail=0):
                if self.isInterruptionRequested():
                    return
                if self.live:
                    self.run_live()
                    return
                recording = record_voice(
                    on_audio=self.report_audio, stop_event=self.stop_event,
                    stop_on_silence=self.automatic)
                if self.isInterruptionRequested():
                    return
            if recording is None:
                return
            self.processing.emit()
            self.audio_wav = recording_to_wav(*recording)
        except Exception as error:
            self.error = str(error)
            logging.getLogger("assistant.voice").exception("Voice input failed")

    def run_live(self):
        import sounddevice as sound
        from src.init.voice import LiveVoiceCapture, recording_to_wav

        device = sound.query_devices(kind="input")
        sample_rate = int(device.get("default_samplerate") or 16000)
        self.capture = LiveVoiceCapture(sample_rate)
        with sound.RawInputStream(samplerate=sample_rate,
                                  blocksize=max(1, int(sample_rate * 0.05)),
                                  device=device["index"], channels=1,
                                  dtype="int16") as stream:
            while not self.stop_event.is_set() and not self.isInterruptionRequested():
                data, overflow = stream.read(max(1, int(sample_rate * 0.05)))
                if overflow:
                    raise RuntimeError("Microphone overflow; restart voice conversation")
                pcm = bytes(data)
                if self.waiting_response.is_set():
                    self.capture.idle = 0.0
                recording = self.capture.feed(pcm)
                self.report_audio(pcm, sample_rate)
                if self.capture.event == "timeout":
                    return
                if self.capture.event == "started":
                    self.speech_started.emit()
                if recording is not None:
                    self.waiting_response.set()
                    self.processing.emit()
                    self.utterance.emit(DesktopVoiceMessage(
                        recording_to_wav(recording, sample_rate), live=True))

    def playback(self, samples, sample_rate):
        capture = self.capture
        if capture is not None:
            capture.playback(samples, sample_rate)

    def report_audio(self, pcm_data, sample_rate):
        import numpy as np

        if (self.waiting_response.is_set() and self.capture is not None
                and not self.capture.started):
            return
        samples = np.frombuffer(pcm_data, dtype="<i2").astype(
            np.float32) / 32768.0
        self.levels.emit(spectrum_levels(samples, sample_rate).tolist())


# noinspection PyBroadException
class AssistantWorker(QObject):
    chunk = Signal(int, str)
    audio = Signal(int, object)
    directory = Signal(str)
    speaking = Signal(int, bool)
    subtitle = Signal(int, str)
    phase = Signal(int, str)
    activity = Signal(int, object)
    task_title = Signal(int, str)
    permission_denied = Signal(int)
    finished = Signal(str)
    git_diff_ready = Signal(str, str)
    failed = Signal(str)
    ready = Signal()
    confirmation_requested = Signal(int, str)
    accepted = Signal(int)
    rejected = Signal(int, str)
    screenshot_requested = Signal(object)
    clipboard_requested = Signal(object)
    exit_requested = Signal()

    def __init__(self, startup_greeting="", *, muted=False):
        super().__init__()
        self.assistant = Assistant()
        self.startup_greeting = startup_greeting
        self.muted = bool(muted)
        self._voice_settings_lock = threading.Lock()
        self.session = SessionLog()
        self.history = self.session.context.messages
        self.confirmation_event = threading.Event()
        self.confirmation_answer = False
        self._confirmation_lock = threading.Lock()
        self._pending_confirmation = None
        self.cancel_event = threading.Event()
        self.command_reply = False
        self.live_capture = None
        self._last_audio_update = 0.0
        self.event_loop = None

    @Slot()
    def initialize(self):
        try:
            self.event_loop = asyncio.new_event_loop()
            self.assistant._initialize_runtime()
            with self._voice_settings_lock:
                self.assistant.voice.set_muted(self.muted)
            if self.startup_greeting:
                voice = self.assistant.voice
                voice.audio_callback = lambda samples, rate: self.report_audio(
                    0, samples, rate)
                voice.speaking_callback = lambda speaking: self.speaking.emit(
                    0, speaking)
                voice.subtitle_callback = lambda text: self.subtitle.emit(0,
                                                                          text)
                try:
                    with desktop_audio():
                        voice.begin_turn()
                        voice.enqueue(self.startup_greeting)
                        voice.wait_until_done()
                except Exception:
                    logging.getLogger("assistant.voice").exception(
                        "Unable to play startup greeting")
                finally:
                    voice.audio_callback = None
                    voice.speaking_callback = None
                    voice.subtitle_callback = None
                    self.speaking.emit(0, False)
            self.directory.emit(str(Path.cwd()))
            self.ready.emit()
        except Exception as error:
            self.failed.emit(str(error))

    def set_muted(self, muted: bool):
        """Apply immediately even while the worker is generating a response."""
        with self._voice_settings_lock:
            self.muted = bool(muted)
            if self.assistant.voice is not None:
                self.assistant.voice.set_muted(self.muted)

    @Slot(int, object)
    def ask(self, turn_id, message):
        try:
            live = (isinstance(message, DesktopVoiceMessage) and message.live
                    and self.live_capture is not None)
            lease = nullcontext() if live else desktop_audio(stop_event=self.cancel_event)
            with lease as audio_lease:
                self._ask(turn_id, message, audio_lease)
        except Exception as error:
            self.rejected.emit(turn_id, str(error))

    def _ask(self, turn_id, message, audio_lease):
        message = DesktopMessage(message) if isinstance(message,
                                                        str) else message
        voice_input = isinstance(message, DesktopVoiceMessage)
        attachment_session = None
        try:
            if message.attachments:
                vision, context = ollama_capabilities(self.assistant.MODEL_NAME)
                attachment_session = AttachmentSession(
                    message, load_config()["attachments"], vision=vision,
                    context_tokens=context)
        except Exception as error:
            self.rejected.emit(turn_id, str(error))
            return
        self.accepted.emit(turn_id)
        prompt = message.transcript.strip() if voice_input else message.text
        try:
            cancel_event = self.cancel_event
            set_confirmation_handler(
                lambda message: self.confirm_command(message, cancel_event,
                                                     turn_id))
            self.command_reply = (not voice_input and not message.attachments
                                  and prompt.casefold().startswith("pwsh:"))
            if cancel_event.is_set():
                self.finished.emit("")
                return
            privacy_result = (self.session.handle_command(prompt)
                              if not voice_input and not message.attachments
                              else None)
            if privacy_result is not None:
                self.finished.emit(str(privacy_result))
                return

            if voice_input and not prompt:
                try:
                    from src.init.voice import transcribe_voice

                    with wave.open(io.BytesIO(message.audio_wav), "rb") as wav:
                        prompt, _ = transcribe_voice(
                            wav.readframes(wav.getnframes()), wav.getframerate(),
                            beam_size=1, vad_filter=False)
                    prompt = prompt.strip()
                except Exception:
                    logging.getLogger("assistant.voice").exception(
                        "Local voice transcript unavailable; attempting native transcription")
                    prompt = self.assistant.transcribe_audio(
                        message.audio_wav, event_loop=self.event_loop)
            if voice_input:
                if cancel_event.is_set():
                    self.finished.emit("")
                    return
                if not prompt:
                    raise RuntimeError(tr("voice.not_transcribed"))
                message = replace(message, transcript=prompt)
            self.session.write(self.assistant.username, message.log_text())

            from src.init.hot_reload import is_reload_command
            if (not voice_input and not message.attachments
                    and is_reload_command(prompt)):
                reply = self.assistant.reload_source()
                self.session.context.add_exchange(prompt, reply)
                self.session.write(self.assistant.name, reply)
                self.finished.emit(reply)
                return
            task_title = ""

            def receive_task_title(title):
                nonlocal task_title
                if not task_title:
                    task_title = title
                self.task_title.emit(turn_id, task_title)

            if task_title:
                self.task_title.emit(turn_id, task_title)

            def receive_surface(surface, title):
                if surface != "response_view":
                    return True
                try:
                    from src.init.visuals.response import request_response_workspace
                    result = request_response_workspace(title or "Response")
                    logging.getLogger("assistant.response").info(
                        "Response workspace result: %s", result)
                    return False
                except Exception:
                    logging.getLogger("assistant.response").exception(
                        "Unable to open response workspace; falling back to chat")
                    return True

            def speaking_changed(speaking):
                if speaking and audio_lease is not None:
                    audio_lease.yield_to_wake_listener()
                self.speaking.emit(turn_id, speaking)

            reply, history = self.assistant.run(
                prompt,
                self.history,
                on_chunk=lambda chunk: self.chunk.emit(turn_id, chunk),
                on_audio=lambda samples, rate: self.report_audio(
                    turn_id, samples, rate),
                on_speaking=speaking_changed,
                on_subtitle=lambda text: self.subtitle.emit(turn_id, text),
                on_phase=lambda phase: self.phase.emit(turn_id, phase),
                on_activity=lambda activity: self.activity.emit(turn_id, activity),
                cancel_event=cancel_event,
                event_loop=self.event_loop,
                attachments=attachment_session,
                session=self.session,
                task_title=task_title,
                on_surface=receive_surface,
                on_task_title=receive_task_title,
                resume_task_id=getattr(message, "resume_task_id", ""))

            self.history[:] = history
            if not self.cancel_event.is_set() and audio_lease is not None:
                audio_lease.reclaim()

            if reply:
                from .session_log import message_status
                task_state = getattr(self.assistant, "task_state", None)
                self.session.write(self.assistant.name, reply,
                                   status=("interrupted" if cancel_event.is_set() else
                                           message_status(task_state.status) if task_state is not None
                                           else "completed"))

            task_state = getattr(self.assistant, "task_state", None)
            if (not cancel_event.is_set() and not self.assistant.shutdown_requested.is_set()
                    and (task_state is None or task_state.status == "complete")):
                from src.init.visuals.git_diff_connector import get_git_patch
                directory = str(Path.cwd())
                patch = get_git_patch(directory)
                if patch:
                    self.git_diff_ready.emit(directory, patch)

            self.finished.emit(reply)

        except Exception as error:
            cause = error.__cause__
            message = tr("ui.error_detail", error=error,
                         cause=cause) if cause is not None else str(
                error)
            self.session.write("System", message, status="error")
            self.failed.emit(message)

        finally:
            self.directory.emit(str(Path.cwd()))
            if self.assistant.shutdown_requested.is_set():
                self.exit_requested.emit()

    def report_audio(self, turn_id, samples, sample_rate):
        if not self.cancel_event.is_set():
            capture = self.live_capture
            if capture is not None:
                capture.playback(samples, sample_rate)
            now = time.monotonic()
            if now - self._last_audio_update < 0.10:
                return
            self._last_audio_update = now
            self.audio.emit(turn_id, spectrum_levels(samples,
                                                     sample_rate).tolist())

    def interrupt(self):
        self.cancel_event.set()
        self.assistant.cancel_active_generation()
        self.resolve_confirmation(False)
        voice = self.assistant.voice
        if voice is not None:
            try:
                voice.stop()
            except Exception:
                logging.getLogger("assistant.voice").exception(
                    "Unable to stop speech immediately")

    @Slot()
    def shutdown(self):
        self.session.close()
        if self.assistant.voice is not None:
            self.assistant.voice.close()
        if self.event_loop is not None:
            self.event_loop.close()

    def confirm_command(self, message: str, cancel_event=None,
                        turn_id=0, context=None) -> bool:
        cancel_event = self.cancel_event if cancel_event is None else cancel_event
        if cancel_event.is_set():
            return False
        self.confirmation_answer = False
        self.confirmation_event.clear()
        pending = {"turn_id": turn_id, "message": message,
                   **(context or {})}
        with self._confirmation_lock:
            self._pending_confirmation = pending
        if cancel_event.is_set():
            with self._confirmation_lock:
                if self._pending_confirmation is pending:
                    self._pending_confirmation = None
            return False
        self.confirmation_requested.emit(turn_id, message)
        try:
            while not self.confirmation_event.wait(0.05):
                if cancel_event.is_set():
                    return False
            accepted = self.confirmation_answer and not cancel_event.is_set()
        finally:
            with self._confirmation_lock:
                if self._pending_confirmation is pending:
                    self._pending_confirmation = None
        if not accepted:
            self.permission_denied.emit(turn_id)
        return accepted

    def resolve_confirmation(self, accepted: bool):
        with self._confirmation_lock:
            if self._pending_confirmation is None:
                return False
            self.confirmation_answer = accepted
            self.confirmation_event.set()
            return True
