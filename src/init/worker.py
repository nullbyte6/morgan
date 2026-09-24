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
import json
import logging
import re
import threading
from pathlib import Path
from urllib.request import Request, urlopen

from PySide6.QtCore import *

from src.init.attachments import (DesktopMessage, DesktopVoiceMessage, AttachmentSession,
    ollama_capabilities)

from src.init.commands import execute_command, set_confirmation_handler
from src.init.config import load_config
from src.init.core import Assistant
from src.init.lang import tr
from src.init.session_log import SessionLog
from src.init.voice_ipc import desktop_audio
from src.init.utils import spectrum_levels


AGENT_PHASES = {
    "PLANNING": "processing",
    "EXECUTING": "executing",
    "VERIFYING": "processing",
    "AWAITING_APPROVAL": "executing",
}


def handle_direct_command(assistant, prompt: str) -> str | None:
    for handler in (
        assistant.directory_cmd,
        assistant.git_cmd,
        assistant.print_file_cmd,
    ):
        result = handler(prompt)
        if result is not None:
            return result
    return None


def requests_response_workspace(prompt: str) -> bool:
    normalized = " ".join(prompt.casefold().split())
    return any(phrase in normalized for phrase in (
        "response workspace",
        "workspace de respuesta",
        "espacio de respuesta",
        "espacio de trabajo de respuesta",
        "panel de respuesta",
    ))


def confirmation_reply(prompt: str) -> bool | None:
    normalized = re.sub(r"[^\w]+", " ", prompt.casefold()).strip()
    if normalized in {"confirmo", "confirmar", "confirm", "confirmed", "yes", "sí", "si"}:
        return True
    if normalized in {"no confirmo", "rechazo", "deny", "denied", "no"}:
        return False
    return None


def select_response_surface(prompt: str, model_name: str) -> str | None:
    """Let the local LLM choose the output surface before generation."""
    if not prompt.strip():
        return None

    schema = {
        "type": "object",
        "properties": {
            "surface": {
                "type": "string",
                "enum": ["chat", "response_view"],
            },
            "title": {"type": "string"},
        },
        "required": ["surface", "title"],
        "additionalProperties": False,
    }

    payload = {
        "model": model_name,
        "stream": False,
        "think": False,
        "format": schema,
        "options": {
            "temperature": 0,
            "num_predict": 96,
        },
        "messages": [
            {
                "role": "system",
                "content": (
                    "Choose how a local desktop assistant should display "
                    "its next answer. Return only the requested JSON. "
                    "Choose response_view when the user explicitly requests "
                    "a separate response workspace, or when a substantial "
                    "explanation, tutorial, documentation, or multiple code "
                    "examples would benefit from a document-like view. "
                    "Choose chat for ordinary conversation, short answers, "
                    "and operational commands. Respect requests to remain "
                    "in the main chat. Interpret the user's meaning in any "
                    "language, not specific keywords. If unsure, choose chat. "
                    "For response_view, provide a short relevant panel title. "
                    "Do not answer the user's actual question."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }

    request = Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urlopen(request, timeout=30) as response:
        result = json.load(response)

    decision = json.loads(result["message"]["content"])
    surface = decision["surface"]
    title = str(decision.get("title") or "").strip()[:72]

    logging.getLogger("arlo.response").info(
        "Surface decision: %s; title=%r", surface, title
    )

    if surface == "response_view":
        return title or "Response"

    return None


class VoiceInputWorker(QThread):
    levels = Signal(object)
    processing = Signal()

    def __init__(self, parent=None, *, automatic=False):
        super().__init__(parent)
        self.automatic = automatic
        self.stop_event = threading.Event()
        self.audio_wav = b""
        self.transcript = ""
        self.error = ""

    def run(self):
        try:
            from src.init.voice import (record_voice, recording_to_wav,
                                        transcribe_voice)

            with desktop_audio(stop_event=self.stop_event, tail=0):
                if self.isInterruptionRequested():
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
            try:
                self.transcript, _ = transcribe_voice(*recording)
            except Exception as error:
                logging.getLogger("arlo.voice").warning(
                    "Voice transcript unavailable; continuing with native audio: %s",
                    error)
        except Exception as error:
            self.error = str(error)

    def report_audio(self, pcm_data, sample_rate):
        import numpy as np

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
    permission_denied = Signal(int)
    finished = Signal(str)
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
        self.history = []
        self.session = SessionLog()
        self.confirmation_event = threading.Event()
        self.confirmation_answer = False
        self._confirmation_lock = threading.Lock()
        self._pending_confirmation = None
        self.cancel_event = threading.Event()
        self.command_reply = False
        self.event_loop = None
        self.agent_orchestrator = None

    @Slot()
    def initialize(self):
        try:
            self.event_loop = asyncio.new_event_loop()
            self.assistant._initialize_runtime()
            self.initialize_agent_orchestrator()
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
                    logging.getLogger("arlo.voice").exception(
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

    def initialize_agent_orchestrator(self):
        from src.init.agent import AgentOrchestrator, AgentStore
        from src.init.agent.pydantic_backend import PydanticAgentBackend
        from src.init.config import HOME_PATH, load_config
        from src.init.tools import TOOLS

        agent_tools = [
            function for function in TOOLS
            if function.__name__ not in {"edit_code", "update_repo"}
        ]
        settings = load_config()["agent"]
        database = Path(settings["database"])
        if not database.is_absolute():
            database = HOME_PATH / database
        store = AgentStore(database)
        interrupted = store.interrupted_runs()
        if interrupted:
            logging.getLogger("arlo.agent").warning(
                "Found %d interrupted autonomous runs", len(interrupted))
        backend = PydanticAgentBackend(
            self.assistant.model, agent_tools,
            base_instructions=(
                self.assistant.current_instructions,
                self.assistant.current_datetime_instructions,
                self.assistant.working_directory_instructions,
            ))
        self.agent_orchestrator = AgentOrchestrator(
            backend, {function.__name__: function for function in agent_tools}, store,
            max_steps=settings["max_steps"],
            max_retries=settings["max_retries"])

    @Slot(int, object)
    def ask(self, turn_id, message):
        try:
            with desktop_audio(stop_event=self.cancel_event) as audio_lease:
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
        prompt = (message.transcript.strip() if voice_input else message.text)
        try:
            cancel_event = self.cancel_event
            set_confirmation_handler(
                lambda message: self.confirm_command(message, cancel_event,
                                                     turn_id))
            self.command_reply = False
            if cancel_event.is_set():
                self.finished.emit("")
                return
            if (isinstance(message, DesktopMessage) and message.agent_mode
                    and not message.attachments
                    and confirmation_reply(prompt) is not None):
                self.session.write(self.assistant.username, message.log_text())
                resumed = self.resolve_confirmation_reply(prompt)
                reply = (
                    "La aprobación se aplicó a la operación pendiente de Forge."
                    if resumed else
                    "No hay ninguna operación de Forge pendiente de aprobación.")
                self.session.write(self.assistant.name, reply)
                self.finished.emit(reply)
                return
            privacy_result = (self.session.handle_command(prompt)
                              if not voice_input and not message.attachments
                              else None)
            if privacy_result is not None:
                self.finished.emit(str(privacy_result))
                return

            self.session.write(self.assistant.username, message.log_text())

            from src.init.hot_reload import is_reload_command
            if (not voice_input and not message.attachments
                    and is_reload_command(prompt)):
                reply = self.assistant.reload_source()
                self.session.write(self.assistant.name, reply)
                self.finished.emit(reply)
                return
            direct_result = (handle_direct_command(self.assistant, prompt)
                             if not voice_input and not message.attachments
                             else None)
            if direct_result is not None:
                self.session.write(self.assistant.name, direct_result)
                self.finished.emit(direct_result)
                return

            if not voice_input and not message.attachments and prompt.casefold().startswith(
                    "pwsh:"):
                self.command_reply = True
                command = prompt[5:].strip()
                raw_result = execute_command(command)
                data = json.loads(raw_result)

                output = data.get("stdout", "")
                error = data.get("stderr", "")

                reply = tr("command.result",
                           status=tr("command.status." + data["status"]),
                           code=data.get("exit_code", "—"), output=output)

                if error:
                    reply += tr("command.stderr", error=error)

                if data["status"] == "error":
                    reply += f"\n\n{data.get('error', '')}"

                self.session.write(self.assistant.name, reply)
                self.finished.emit(reply)
                return

            if isinstance(message, DesktopMessage) and message.agent_mode:
                if self.session.private:
                    reply = "Agent Mode is unavailable in private mode because autonomous runs persist."
                    self.finished.emit(reply)
                    return
                self.run_agent_mode(
                    turn_id, message.log_text(), cancel_event)
                return


            response_title = None

            try:
                response_title = select_response_surface(
                    prompt, self.assistant.MODEL_NAME)
            except Exception:
                logging.getLogger("arlo.response").exception(
                    "Unable to select response surface; falling back to chat")

            if cancel_event.is_set():
                self.finished.emit("")
                return

            if response_title is not None:
                from src.init.visuals.response import request_response_workspace
                result = request_response_workspace(response_title)
                logging.getLogger("arlo.response").info(
                    "Response workspace result: %s", result)

            def speaking_changed(speaking):
                if speaking:
                    audio_lease.yield_to_wake_listener()
                self.speaking.emit(turn_id, speaking)

            reply, self.history = self.assistant.run_desktop_turn(
                prompt,
                self.history,
                on_chunk=lambda chunk: self.chunk.emit(turn_id, chunk),
                on_audio=lambda samples, rate: self.report_audio(turn_id,
                                                                 samples, rate),
                on_speaking=speaking_changed,
                on_subtitle=lambda text: self.subtitle.emit(turn_id, text),
                on_phase=lambda phase: self.phase.emit(turn_id, phase),
                cancel_event=cancel_event,
                event_loop=self.event_loop,
                attachments=attachment_session, session=self.session,
                audio_input=(message.audio_wav
                             if voice_input and not prompt else None))
            if not self.cancel_event.is_set():
                audio_lease.reclaim()

            if reply:
                self.session.write(self.assistant.name, reply,
                                   status="interrupted" if cancel_event.is_set() else "completed")

            self.finished.emit(reply)

        except Exception as error:
            cause = error.__cause__
            message = tr("ui.error_detail", error=error,
                         cause=cause) if cause is not None else str(
                error)
            self.session.write("System", message)
            self.failed.emit(message)

        finally:
            self.directory.emit(str(Path.cwd()))
            if self.assistant.shutdown_requested.is_set():
                self.exit_requested.emit()

    def run_agent_mode(self, turn_id: int, prompt: str, cancel_event) -> None:
        from src.init.agent import EventType, ExecutionState

        if requests_response_workspace(prompt):
            try:
                from src.init.visuals.response import request_response_workspace
                result = request_response_workspace("Agent Result")
                logging.getLogger("arlo.response").info(
                    "Agent response workspace result: %s", result)
            except Exception:
                logging.getLogger("arlo.response").exception(
                    "Unable to open the requested agent response workspace")

        approval_context = {}

        def event_received(event):
            if event.type == EventType.STATE_CHANGED:
                phase = AGENT_PHASES.get(event.payload.get("to"))
                if phase:
                    self.phase.emit(turn_id, phase)
            elif event.type == EventType.APPROVAL_REQUESTED:
                approval_context.clear()
                approval_context.update({
                    "run_id": event.run_id,
                    "step_id": event.step_id,
                    "tool_name": event.payload.get("tool_name"),
                })
            elif event.type == EventType.APPROVAL_RESOLVED:
                approval_context.clear()

        result = self.event_loop.run_until_complete(self.agent_orchestrator.run(
            prompt,
            cancel_event=cancel_event,
            approval=lambda message: self.confirm_command(
                message, cancel_event, turn_id, approval_context),
            on_event=event_received,
            working_directory=str(Path.cwd()),
        ))
        if result.state == ExecutionState.COMPLETED:
            reply = result.response
        elif result.state == ExecutionState.CANCELLED:
            reply = ""
        else:
            phase = f" during {result.failure_phase}" if result.failure_phase else ""
            reply = (
                f"Agent run {result.state.value.lower()}{phase} "
                f"(run {result.run_id}): {result.error or 'No result'}")
        if reply:
            self.chunk.emit(turn_id, reply)
            self.session.write(
                self.assistant.name, reply,
                status="completed" if result.state == ExecutionState.COMPLETED else "error")
        self.finished.emit(reply)

    def report_audio(self, turn_id, samples, sample_rate):
        if not self.cancel_event.is_set():
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
                logging.getLogger("arlo.voice").exception(
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

    def resolve_confirmation_reply(self, prompt: str) -> bool:
        accepted = confirmation_reply(prompt)
        if accepted is None:
            return False
        return self.resolve_confirmation(accepted)
