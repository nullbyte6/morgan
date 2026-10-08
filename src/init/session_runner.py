#  Copyright (c) 2026 Diego.
#
#  SPDX-License-Identifier: GPL-3.0-or-later
#
#  This file is part of morgan.
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
"""One conversation session's turn execution, independent of any interface toolkit."""
import asyncio
import io
import itertools
import logging
import threading
import time
import wave
from contextlib import nullcontext
from dataclasses import replace

from src.init.attachments import (DesktopMessage, DesktopVoiceMessage, AttachmentSession,
    ollama_capabilities)

from src.init.commands import set_confirmation_handler
from src.init.config import PermissionMode, load_config
from src.init.core import Assistant
from src.init.events import Event
from src.init import latency
from src.init.file_tags import expand_file_tags
from src.init.lang import tr
from src.init.session_log import SessionLog, is_local_command
from src.init.voice_ipc import desktop_audio
from src.init.utils import spectrum_levels
from src.init.voice import SpokenReference, last_reply_text, strip_echo


# noinspection PyBroadException
class SessionRunner:
    """Owns the assistant session and reports progress through Event signals.

    Interfaces call initialize, ask and shutdown from one worker
    thread, and interrupt or resolve_confirmation from any thread.
    """
    CONFIRMATION_TIMEOUT = 30
    report_git_diff = True
    chunk = Event()
    audio = Event()
    directory = Event()
    speaking = Event()
    subtitle = Event()
    transcribed = Event()
    phase = Event()
    activity = Event()
    task_title = Event()
    permission_denied = Event()
    finished = Event()
    git_diff_ready = Event()
    failed = Event()
    ready = Event()
    confirmation_requested = Event()
    confirmation_closed = Event()
    accepted = Event()
    rejected = Event()
    screenshot_requested = Event()
    clipboard_requested = Event()
    exit_requested = Event()
    _confirmation_ids = itertools.count(1)

    def __init__(self, greet=False, *, muted=False, session_key=None, primary=True):
        self.assistant = Assistant()
        self.greet = greet
        self.muted = bool(muted)
        self.session_key = session_key
        self.primary = primary
        self.speech_owner = False
        self._voice_settings_lock = threading.Lock()
        self.session = SessionLog()
        self.history = self.session.context.messages
        self.confirmation_event = threading.Event()
        self.confirmation_answer = False
        self._confirmation_lock = threading.Lock()
        self._pending_confirmation = None
        self.permission_mode = PermissionMode.ASK
        self.cancel_event = threading.Event()
        self.command_reply = False
        self.live_capture = None
        self.spoken = SpokenReference()
        self._last_audio_update = 0.0
        self.event_loop = None

    def initialize(self):
        try:
            self.event_loop = asyncio.new_event_loop()
            self.assistant._initialize_runtime()
            with self._voice_settings_lock:
                self.assistant.voice.set_muted(self.muted)
            greeting = self.assistant.generate_greeting() if self.greet else ""
            if greeting:
                voice = self.assistant.voice
                voice.audio_callback = lambda samples, rate: self.report_audio(
                    0, samples, rate)
                voice.speaking_callback = lambda speaking: self.speaking.emit(
                    0, speaking)
                voice.subtitle_callback = lambda text: self.voiced(0, text)
                try:
                    with desktop_audio():
                        voice.begin_turn()
                        voice.enqueue(greeting)
                        voice.wait_until_done()
                except Exception:
                    logging.getLogger("assistant.voice").exception(
                        "Unable to play startup greeting")
                finally:
                    voice.audio_callback = None
                    voice.speaking_callback = None
                    voice.subtitle_callback = None
                    self.speaking.emit(0, False)
            self.directory.emit(self.session.context.working_directory)
            self.ready.emit()
        except Exception as error:
            self.failed.emit(str(error))

    def voiced(self, turn_id, text):
        self.spoken.add(text)
        self.subtitle.emit(turn_id, text)

    def echo_reference(self):
        return " ".join(filter(None, (self.spoken.text(), last_reply_text(self.history))))

    def set_muted(self, muted: bool):
        """Apply immediately even while the worker is generating a response."""
        with self._voice_settings_lock:
            self.muted = bool(muted)
            if self.assistant.voice is not None:
                self.assistant.voice.set_muted(self.muted)

    def ask(self, turn_id, message):
        from src.init import brain
        brain.set_working_directory_owner(self.session.context)
        try:
            live = (isinstance(message, DesktopVoiceMessage) and message.live
                    and self.live_capture is not None)
            lease = (nullcontext() if live
                     else desktop_audio(stop_event=self.cancel_event))
            with lease as audio_lease:
                self._ask(turn_id, message, audio_lease)
        except Exception as error:
            self.silence()
            self.rejected.emit(turn_id, str(error))
        finally:
            if self.cancel_event.is_set():
                self.silence()
            self.speech_owner = False
            self.assistant.release_speech(self)

    def silence(self):
        voice = self.assistant.voice
        if voice is not None and self.speech_owner:
            try:
                voice.stop()
            except Exception:
                logging.getLogger("assistant.voice").exception(
                    "Unable to stop speech")

    def claim_speech(self):
        self.speech_owner = self.assistant.acquire_speech(self)
        return self.speech_owner

    def show_response_surface(self, title):
        """Open a dedicated response surface; return True to keep it in the chat."""
        return True

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
        if not voice_input:
            latency.discard()
        try:
            self.session.context.task_state = None
            cancel_event = self.cancel_event
            set_confirmation_handler(
                lambda message: self.confirm_command(message, cancel_event,
                                                     turn_id))
            self.command_reply = (not voice_input and not message.attachments
                                  and prompt.casefold().startswith("pwsh:"))
            if cancel_event.is_set():
                self.finished.emit("")
                return
            partial = getattr(message, "partial", None) if voice_input else None
            if partial is not None and not prompt:
                prompt = partial.wait(cancel_event)
            if voice_input and not prompt:
                try:
                    from src.init.voice import transcribe_voice

                    with wave.open(io.BytesIO(message.audio_wav), "rb") as wav:
                        prompt, _ = transcribe_voice(
                            wav.readframes(wav.getnframes()), wav.getframerate(),
                            beam_size=1, vad_filter=False)
                    prompt = prompt.strip()
                except Exception as error:
                    logging.getLogger("assistant.voice").exception(
                        "Local voice transcript unavailable")
                    raise RuntimeError(tr("voice.transcription_failed")) from error
            if voice_input:
                if cancel_event.is_set():
                    self.finished.emit("")
                    return
                if not prompt:
                    raise RuntimeError(tr("voice.not_transcribed"))
                prompt = strip_echo(prompt, self.echo_reference())
                if not prompt:
                    self.finished.emit("")
                    return
                latency.mark("transcript_ready")
                message = replace(message, transcript=prompt)
                self.transcribed.emit(turn_id, prompt)
            local_command = (not voice_input and not message.attachments
                             and is_local_command(prompt))
            if not local_command:
                self.session.write(self.assistant.username, message.log_text())

            from src.init.hot_reload import is_reload_command
            if (not voice_input and not message.attachments
                    and is_reload_command(prompt)):
                reply = self.assistant.reload_source()
                self.session.context.add_exchange(prompt, reply)
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
                return self.show_response_surface(title)

            def speaking_changed(speaking):
                if speaking:
                    latency.mark("first_audio")
                if speaking and audio_lease is not None:
                    audio_lease.yield_to_wake_listener()
                self.speaking.emit(turn_id, speaking)

            reply, history = self.assistant.run(
                prompt if voice_input else expand_file_tags(prompt, self.session.context.working_directory),
                self.history,
                on_chunk=lambda chunk: self.chunk.emit(turn_id, chunk),
                on_audio=lambda samples, rate: self.report_audio(
                    turn_id, samples, rate),
                on_speaking=speaking_changed,
                on_subtitle=lambda text: self.voiced(turn_id, text),
                on_phase=lambda phase: self.phase.emit(turn_id, phase),
                on_activity=lambda activity: self.activity.emit(turn_id, activity),
                cancel_event=cancel_event,
                event_loop=self.event_loop,
                attachments=attachment_session,
                session=self.session,
                task_title=task_title,
                on_surface=receive_surface,
                on_task_title=receive_task_title,
                acquire_speech=self.claim_speech,
                resume_task_id=getattr(message, "resume_task_id", ""))

            self.history[:] = history
            if not self.cancel_event.is_set() and audio_lease is not None:
                audio_lease.reclaim()

            if reply and not local_command:
                from .session_log import message_status
                task_state = self.session.context.task_state
                self.session.write(self.assistant.name, reply,
                                   status=("interrupted" if cancel_event.is_set() else
                                           message_status(task_state.status) if task_state is not None
                                           else "completed"))

            task_state = self.session.context.task_state
            if (self.report_git_diff and not cancel_event.is_set()
                    and not self.assistant.shutdown_requested.is_set()
                    and (task_state is None or task_state.status == "complete")):
                from src.init.visuals.git_diff_connector import get_git_patch
                directory = self.session.context.working_directory
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
            self.silence()
            self.failed.emit(message)

        finally:
            self.directory.emit(self.session.context.working_directory)
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
        self.assistant.cancel_active_generation(self.session.context)
        self.resolve_confirmation(False)
        voice = self.assistant.voice
        if voice is not None and (self.speech_owner or self.assistant.speech_unowned()):
            try:
                voice.stop()
            except Exception:
                logging.getLogger("assistant.voice").exception(
                    "Unable to stop speech immediately")

    def shutdown(self):
        self.session.close()
        if self.primary and self.assistant.voice is not None:
            self.assistant.voice.close()
        if self.event_loop is not None:
            self.assistant.release_event_loop(self.event_loop)
            self.event_loop.close()

    def set_permission_mode(self, mode):
        self.permission_mode = PermissionMode(mode)

    def confirm_command(self, message: str, cancel_event=None,
                        turn_id=0, context=None) -> bool:
        cancel_event = self.cancel_event if cancel_event is None else cancel_event
        if cancel_event.is_set():
            return False
        log = logging.getLogger("assistant.permissions")
        request_id = next(self._confirmation_ids)
        if self.permission_mode is PermissionMode.AUTO:
            log.info("Confirmation %s for turn %s required; approved automatically by permission mode %s",
                     request_id, turn_id, PermissionMode.AUTO.value)
            return True
        self.confirmation_answer = False
        self.confirmation_event.clear()
        pending = {"turn_id": turn_id, "message": message,
                   **(context or {}), "id": request_id}
        with self._confirmation_lock:
            self._pending_confirmation = pending
        if cancel_event.is_set():
            with self._confirmation_lock:
                if self._pending_confirmation is pending:
                    self._pending_confirmation = None
            return False
        deadline = time.monotonic() + self.CONFIRMATION_TIMEOUT
        self.confirmation_requested.emit(turn_id, message, request_id,
                                         self.CONFIRMATION_TIMEOUT)
        try:
            while not self.confirmation_event.wait(0.05):
                if cancel_event.is_set():
                    log.info("Confirmation %s for turn %s cancelled", request_id, turn_id)
                    return False
                if time.monotonic() >= deadline:
                    with self._confirmation_lock:
                        expired = not self.confirmation_event.is_set()
                        if expired:
                            self._pending_confirmation = None
                    if expired:
                        break
            else:
                expired = False
            accepted = (not expired and self.confirmation_answer
                        and not cancel_event.is_set())
        finally:
            with self._confirmation_lock:
                if self._pending_confirmation is pending:
                    self._pending_confirmation = None
            self.confirmation_closed.emit(request_id)
        log.info("Confirmation %s for turn %s %s", request_id, turn_id,
                 "timed out and was rejected" if expired else
                 "accepted by the user" if accepted else "rejected by the user")
        if not accepted:
            self.permission_denied.emit(turn_id)
        return accepted

    def resolve_confirmation(self, accepted: bool, request_id=None):
        with self._confirmation_lock:
            pending = self._pending_confirmation
            if (pending is None or self.confirmation_event.is_set()
                    or request_id is not None and pending["id"] != request_id):
                return False
            self.confirmation_answer = accepted
            self.confirmation_event.set()
            return True
