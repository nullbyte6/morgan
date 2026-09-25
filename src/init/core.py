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
import logging
import json
import os
import random
import re
import subprocess
import threading
import time
from contextlib import nullcontext
from datetime import datetime
from getpass import getuser

from pydantic_ai import Agent, Tool

from src.init.console import DebugConsole
from src.init.voice_client import VoiceClient

# noinspection PyBroadException
class Assistant:
    """One shared assistant; reading its identity never
    starts the model or UI."""
    name = "Arlo"
    voice: VoiceClient = None
    _instance = None
    _instance_lock = threading.Lock()
    debug_console = None

    def __new__(cls):
        with cls._instance_lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance.terminal_ui = None
                instance.agent = None
                instance.provider = None
                instance.audio_model = None
                instance.audio_model_name = None
                instance.shutdown_requested = threading.Event()
                instance._active_cancellation_token = None
                instance.voice = None
                instance.debug_console = None
                instance._reload_lock = threading.Lock()
                instance.username = getuser().capitalize()
                instance.typewriter_delay_seconds = float(
                    os.environ.get("TYPEWRITER_DELAY", "0"))
                cls._instance = instance
            return cls._instance

    @property
    def startup_greeting(self) -> str:
        from src.init.lang import tr
        return tr(f"greeting.{random.randrange(6)}",
                  username=self.username, name=self.name)


    @property
    def banner(self):
        from pyfiglet import figlet_format
        return figlet_format(self.name.strip('o'), font="4max", width=128)

    def _initialize_runtime(self):
        if self.agent is not None:
            return
        os.environ["PYDANTIC_AI_NO_BANNER"] = "1"
        os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
        from pydantic_ai import Agent, Tool
        from pydantic_ai.models.ollama import OllamaModel
        from pydantic_ai.providers.ollama import OllamaProvider

        for logger_name in (
                "httpx",
                "httpcore",
                "httpcore2",
                "openai",
                "pydantic_ai"):
            logger = logging.getLogger(logger_name)
            logger.setLevel(logging.CRITICAL)
            logger.propagate = False

        from src.init.brain import MODEL_NAME
        from src.init.tools import TOOLS

        if self.voice is None:
            self.voice = VoiceClient(audio_callback=(
                    self.terminal_ui.update_audio_levels
                    if self.terminal_ui is not None
                    else None))

        self.MODEL_NAME = MODEL_NAME
        self.model_settings = {
            "openai_reasoning_effort": "none",
            "temperature": 0.2,
        }

        self.provider = OllamaProvider(base_url="http://localhost:11434/v1")
        self.model = OllamaModel(
            self.MODEL_NAME,
            provider=self.provider,
            profile={"openai_chat_supports_multiple_system_messages": False},
            settings=self.model_settings)

        self.agent = Agent(
            model=self.model,
            tools=[Tool(function, sequential=True) for function in TOOLS])

        self.agent.instructions(self.current_instructions)
        self.agent.instructions(self.current_datetime_instructions)
        self.agent.instructions(self.working_directory_instructions)
        from src.init.memory.integration import memory_instructions
        self.agent.instructions(memory_instructions)
        self.agent.instructions(
            "When the user explicitly requests a flowchart, diagram, "
            "workflow, decision tree, or process visualization, call "
            "render_flowchart with newly supplied nodes and edges. "
            "It does not require an existing diagram. Do not claim "
            "this capability is unavailable.")

    def reload_source(self) -> str:
        """Reload source modules and rebuild the model and tools for next turn."""
        with self._reload_lock:
            from src.init.hot_reload import reload_project_modules

            reloaded, errors = reload_project_modules()
            from src.init.brain import MODEL_NAME
            self.MODEL_NAME = MODEL_NAME
            self.audio_model = None
            self.audio_model_name = None

            if self.agent is not None:
                from pydantic_ai.models.ollama import OllamaModel
                from src.init.tools import TOOLS

                self.model = OllamaModel(
                    self.MODEL_NAME, provider=self.provider,
                    profile={"openai_chat_supports_multiple_system_messages": False},
                    settings=self.model_settings)
                self.agent = Agent(
                    model=self.model,
                    tools=[Tool(function, sequential=True)
                           for function in TOOLS])
                self.agent.instructions(self.current_instructions)
                self.agent.instructions(self.current_datetime_instructions)
                self.agent.instructions(self.working_directory_instructions)
                from src.init.memory.integration import memory_instructions
                self.agent.instructions(memory_instructions)

                self.agent.instructions(
                    "When the user explicitly requests a flowchart, diagram, "
                    "workflow, decision tree, or process visualization, call "
                    "render_flowchart with newly supplied nodes and edges. "
                    "It does not require an existing diagram. Do not claim "
                    "this capability is unavailable.")

            summary = f"Reloaded {len(reloaded)} source modules"
            if errors:
                summary += "; failures: " + " | ".join(errors)
            else:
                summary += "; the refreshed tools will be used on the next turn."
            return summary

    def suspend_terminal(self):
        if self.terminal_ui is None:
            return nullcontext()
        return self.terminal_ui.suspend()

    def stream(self, chunks, session=None) -> str:
        """Consume assistant output without rendering it in TerminalUI."""
        from src.init.output import chunks_group
        from src.init.colors import ASSISTANT_COLOR, RESET_COLOR

        source = [chunks] if isinstance(chunks, str) else chunks
        displayed = []

        if self.terminal_ui is not None:
            for chunk in source:
                displayed.append(chunk)
        else:
            sys.stdout.write(ASSISTANT_COLOR)

            for chunk in chunks_group(source, color=True):
                displayed.append(chunk)

                if self.typewriter_delay_seconds:
                    for character in chunk:
                        sys.stdout.write(character)
                        sys.stdout.flush()
                        time.sleep(self.typewriter_delay_seconds)
                else:
                    sys.stdout.write(chunk)
                    sys.stdout.flush()

            sys.stdout.write(f"{RESET_COLOR}\n")
            sys.stdout.flush()

        reply = "".join(displayed)

        if session is not None:
            session.write(self.name, reply)

        return reply

    def speak(self, chunks) -> str:
        """Stream LLM output invisibly and feed complete phrases to TTS."""
        from src.init.streaming import SpeechBuffer
        self.voice.begin_turn()
        buffer = SpeechBuffer()
        reply = []
        for chunk in chunks:
            if not chunk:
                continue
            if not reply and self.terminal_ui is not None:
                self.terminal_ui.set_thinking(False)
            reply.append(chunk)
            for phrase in buffer.feed(chunk):
                self.voice.enqueue(phrase)
        for phrase in buffer.finish():
            self.voice.enqueue(phrase)
        return "".join(reply)

    def directory_cmd(self, command: str) -> str | None:
        """Handle standalone cd/chdir commands without a model or shell call."""
        from src.init.brain import change_directory
        match = re.fullmatch(r"(?:cd|chdir)(?=\s|\.|\\|$)\s*(.*)",
                             command.strip(), flags=re.IGNORECASE)
        if match is None:
            return None
        path = match.group(1)
        path = re.sub(r"^/d(?:\s+|$)", "", path, count=1, flags=re.IGNORECASE)
        return change_directory(path)


    def git_cmd(self, command: str) -> str | None:
        """Execute exact supported Git commands through the existing tools."""
        from src.init import brain

        commands = {
            "git push": brain.git_push,
            "git status": brain.git_status,
            "git diff": brain.git_diff,
            "git log": brain.git_log,
        }
        function = commands.get(command.strip())
        return function() if function is not None else None

    def print_file_cmd(self, command: str) -> str | None:
        """Print explicit requests for a file's contents without using the LLM."""
        patterns = (
            r"(?:imprime|muestra|enseña|lee|print|show|cat)\s+(?:el\s+contenido\s+de\s+)?(.+)",
            r"(?:muéstrame|enséñame)\s+(?:el\s+contenido\s+de\s+)?(.+)",
        )

        for pattern in patterns:
            match = re.fullmatch(pattern,
                                 command.strip(),
                                 flags=re.IGNORECASE)

            if match is None:
                continue

            path = match.group(1).strip().strip('"').strip("'")
            if not path:
                return None

            from src.init.brain import read_file
            return read_file(path)

        return None

    def application_opening_request(self, prompt: str) -> str | None:
        match = re.fullmatch(
            r"\s*(?:arlo[,:]?\s*)?(?:necesito que\s+)?(?:puedes\s+)?"
            r"(?:abre|abreme|ábreme|abrir|open|launch|inicia|ejecuta)\s+"
            r"(?:el|la)?\s*(.+?)\s*[.!]?\s*",
            prompt, re.IGNORECASE)
        if match is None:
            return None
        application = match.group(1).strip()
        return application or None

    def printlns(self, content: str) -> None:
        if self.terminal_ui is not None:
            with self.terminal_ui.suspend():
                self.debug_console.print_to_ui(content)
        else:
            print(content)

    def build_user_prompt(self) -> str:
        """Show the current location and live Git branch,
        including unborn branches."""
        from src.init import brain
        from src.init.brain import get_working_directory
        if not brain.should_show_working_directory():
            return f">> "

        directory = get_working_directory()
        branch = ""
        try:
            result = subprocess.run(
                ["git", "-C", directory, "symbolic-ref", "--quiet", "--short",
                 "HEAD"],
                capture_output=True, text=True, errors="replace", timeout=2,
            )
            if result.returncode == 0:
                branch = result.stdout.strip()
            elif result.returncode == 1:
                result = subprocess.run(
                    ["git", "-C", directory, "rev-parse", "--short", "HEAD"],
                    capture_output=True, text=True, errors="replace", timeout=2,
                )
                if result.returncode == 0:
                    branch = f"detached:{result.stdout.strip()}"
        except (OSError, subprocess.TimeoutExpired):
            pass
        suffix = f" ({branch})" if branch else ""
        return f">> {directory}{suffix} > "


    def read_user_input(self, prompt: str | None = None,
                        placeholder: str = "") -> str:
        """Read input with a normal prompt and the user's typed text in green."""
        from src.init.colors import RESET_COLOR, USER_COLOR

        if prompt is None:
            prompt = self.build_user_prompt()

        if self.terminal_ui is not None:
            return self.terminal_ui.read_input(
                prompt=prompt,
                placeholder=placeholder)

        sys.stdout.write(f"{RESET_COLOR}{prompt}{USER_COLOR}")
        sys.stdout.flush()

        try:
            return input()
        finally:
            sys.stdout.write(RESET_COLOR)
            sys.stdout.flush()

    def current_instructions(self) -> str:
        from src.init import rules
        return (rules.current_instructions()
                + "\nApplication execution: call the native open_application tool "
                "for requested apps. Writing an action JSON or describing a call "
                "does not execute it. Only report an app as open when its tool "
                "result has opened=true. If launch_requested=true but opened=false, "
                "explain that the launch could not be confirmed and do not repeat it. "
                "Conversation messages can contain local artifact links replacing large "
                "tool results. Use read_file on a linked artifact when its raw "
                "contents are needed for the current reasoning.")

    def working_directory_instructions(self) -> str:
        from src.init.brain import get_working_directory
        return f"Current working directory for this turn: {get_working_directory()}"

    def current_datetime_instructions(self) -> str:
        """Provide the actual local date and time on every model run."""
        now = datetime.now().astimezone()

        return (
            f"Current local date and time: {now.isoformat(timespec='seconds')}\n"
            f"Current year: {now.year}\n"
            f"Current timezone: {now.tzname()}\n"
            "This is the authoritative current date and time for this turn. "
            "Use it for date-related reasoning. "
            "Do not assume that your training knowledge is current. "
            "For events, releases, prices, or other facts that may have changed "
            "since your training cutoff, use search_web and verify reliable "
            "sources before answering. "
            "Never invent events or claim that a future event has already occurred "
            "without supporting evidence."
        )


    def run_desktop_turn(self, prompt: str, history: list, on_chunk=None,
                         on_audio=None, on_speaking=None, on_subtitle=None,
                         on_phase=None,
                         cancel_event=None, event_loop=None, attachments=None,
                         session=None, audio_input=None):
        """Cancel the model stream and queued speech before accepting steering."""
        import asyncio
        from src.init import brain
        from src.init.streaming import SpeechBuffer
        from pydantic_ai import CancellationToken
        from pydantic_ai.messages import (BinaryContent, ModelRequest,
                                          ModelResponse, TextPart,
                                          UserPromptPart)

        application = self.application_opening_request(prompt)
        if application is not None and audio_input is None and not attachments:
            from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
            from src.init.brain import open_application

            result = open_application(application)
            try:
                details = json.loads(result)
            except (TypeError, json.JSONDecodeError):
                details = None
            if isinstance(details, dict) and details.get("opened") is True:
                reply = f"Aplicación abierta: {details.get('application', application)}."
            elif isinstance(details, dict) and details.get("launch_requested") is True:
                reply = ("Windows aceptó la solicitud para abrir "
                         f"{details.get('application', application)}.")
            elif isinstance(details, dict):
                reply = details.get("error", result)
            else:
                reply = result
            if on_chunk is not None:
                on_chunk(reply)
            return reply, [*history,
                           ModelRequest(parts=[UserPromptPart(prompt)]),
                           ModelResponse(parts=[TextPart(reply)])]

        self._initialize_runtime()
        self.voice.audio_callback = on_audio
        self.voice.speaking_callback = on_speaking
        self.voice.subtitle_callback = on_subtitle
        self.voice.begin_turn()
        cancel_event = cancel_event if cancel_event is not None else threading.Event()
        cancellation_token = CancellationToken()
        self._active_cancellation_token = cancellation_token
        reply = []
        completed_history = None
        execution_started = False
        stream_messages = list(history)
        defer_output = True

        if attachments:
            attachments.reserve_history(history)
        turn_model = None
        turn_model_settings = {"temperature": brain.load_config()["temperature"]}
        model_prompt = attachments.prompt() if attachments else prompt
        # Select the audio model only for a turn that actually contains audio.
        # Looking through history makes a later text turn inherit audio mode.
        voice_model_active = audio_input is not None
        if audio_input is not None:
            model_prompt = [BinaryContent(data=audio_input, media_type="audio/wav")]
        if voice_model_active:
            from pydantic_ai.models.ollama import OllamaModel
            from src.init.config import load_dev_file

            audio_model_name = load_dev_file()["audio_model"]
            if self.audio_model is None or self.audio_model_name != audio_model_name:
                self.audio_model_name = audio_model_name
                self.audio_model = OllamaModel(
                    self.audio_model_name, provider=self.provider,
                    profile={"openai_chat_supports_multiple_system_messages": False},
                    settings={"openai_reasoning_effort": "low"})
            turn_model = self.audio_model
            turn_model_settings["openai_reasoning_effort"] = "low"
        attachment_tools = [attachments.toolset()] if attachments else []

        async def generate():
            nonlocal completed_history, stream_messages, execution_started
            from pydantic_ai.messages import (PartStartEvent, PartDeltaEvent,
                                              TextPartDelta, FunctionToolCallEvent,
                                              FunctionToolResultEvent)
            buffer = SpeechBuffer()

            async def stream_events(ctx, events):
                nonlocal stream_messages
                stream_messages = ctx.messages
                async for event in events:
                    if cancel_event.is_set():
                        return
                    chunk = ""
                    if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
                        chunk = event.part.content
                    elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
                        chunk = event.delta.content_delta
                    if isinstance(event, FunctionToolCallEvent):
                        logging.getLogger("arlo.tools").info(
                            "Executing %s (%s)", event.part.tool_name, event.part.tool_call_id)
                        if on_phase is not None:
                            on_phase("executing")
                    elif isinstance(event, FunctionToolResultEvent):
                        logging.getLogger("arlo.tools").info(
                            "Tool result: %s (%s)", event.part.tool_name,
                            event.part.tool_call_id)
                        if on_phase is not None:
                            on_phase("processing")
                    if chunk and not defer_output:
                        reply.append(chunk)
                        if on_chunk is not None:
                            on_chunk(chunk)
                        for phrase in buffer.feed(chunk):
                            self.voice.enqueue(phrase)

            if cancel_event.is_set():
                return
            execution_started = True
            result = await self.agent.run(
                model_prompt,
                message_history=history,
                toolsets=attachment_tools,
                model=turn_model,
                model_settings=turn_model_settings,
                cancellation_token=cancellation_token,
                event_stream_handler=stream_events
            )

            completed_history = result.new_messages()
            if session is not None:
                completed_history = session.context.externalize_messages(completed_history)
            if defer_output and not cancel_event.is_set():
                output = result.output
                if session is not None:
                    for message in reversed(completed_history):
                        text_parts = [part.content for part in message.parts
                                      if isinstance(part, TextPart)]
                        if text_parts:
                            output = "".join(text_parts)
                            break
                reply.append(output)
                if on_chunk is not None:
                    on_chunk(output)
                for phrase in buffer.feed(output):
                    self.voice.enqueue(phrase)
            for phrase in buffer.finish():
                if not cancel_event.is_set():
                    self.voice.enqueue(phrase)
            self.voice.request_done()
            while not self.voice.is_done():
                await asyncio.sleep(0.02)

        async def run():
            task = asyncio.create_task(generate())
            try:
                while not task.done():
                    if cancel_event.is_set():
                        self.voice.stop()
                        task.cancel()
                        break
                    await asyncio.sleep(0.02)
                try:
                    await task
                except asyncio.CancelledError:
                    if not cancel_event.is_set():
                        raise
                if cancel_event.is_set():
                    self.voice.stop()
            except BaseException:
                task.cancel()
                try:
                    self.voice.stop()
                except Exception:
                    pass
                await asyncio.gather(task, return_exceptions=True)
                raise

        from src.init.attachments import active_attachments
        attachment_token = active_attachments.set(attachments)
        try:
            with session.memory_scope() if session is not None else nullcontext():
                if event_loop is None:
                    asyncio.run(run())
                else:
                    event_loop.run_until_complete(run())
        finally:
            self._active_cancellation_token = None
            active_attachments.reset(attachment_token)
            self.voice.audio_callback = None
            self.voice.speaking_callback = None
            self.voice.subtitle_callback = None
            if on_speaking is not None:
                on_speaking(False)

        text = "".join(reply)
        if cancel_event.is_set():
            if not execution_started:
                return "", history
            messages = stream_messages or list(history) + [ModelRequest(parts=[UserPromptPart(model_prompt)])]
            safe = list(history)
            pending = set()
            segment = []
            for message in messages[len(history):]:
                segment.append(message)
                for part in message.parts:
                    if part.part_kind == "tool-call":
                        pending.add(part.tool_call_id)
                    elif part.part_kind in ("tool-return", "retry-prompt"):
                        pending.discard(getattr(part, "tool_call_id", None))
                if not pending:
                    safe.extend(segment)
                    segment = []
            if len(safe) > len(history) and isinstance(safe[-1], ModelResponse) and any(
                    isinstance(part, TextPart) for part in safe[-1].parts):
                safe.pop()
            safe.append(ModelResponse(parts=[TextPart(
                (text + "\n" if text else "") +
                "[Response interrupted by the user. Speech may have stopped before "
                "all displayed text was spoken. Tools already started may have completed; "
                "inspect current state before retrying. Follow the user's next instruction.]")]))
            return text, safe
        return text, self._merge_message_history(history, completed_history)

    @staticmethod
    def _merge_message_history(history: list, completed_history: list | None) -> list:
        if not completed_history:
            return list(history)
        return [*history, *completed_history]

    def cancel_active_generation(self):
        """Cancel the active PydanticAI run from the worker thread."""
        token = self._active_cancellation_token
        if token is not None:
            token.cancel()

    def run(self):
        try:
            self.debug_console = DebugConsole()
            self.debug_console.start()
            self.debug_console.configure_logging()
            logging.getLogger("arlo").info(tr('agent.arlo_is_awake'))

        except (EOFError, KeyboardInterrupt):
            pass
