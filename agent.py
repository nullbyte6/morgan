#! /usr/bin/env python3
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

# type: ignore
"""Arlo's main entry to the whole brain, no pun intended
see how Arlo works and engineers from here"""
from src.init.lang import tr
import json
import logging
import os

os.environ["TORCH_CPP_LOG_LEVEL"] = "ERROR"
os.environ["TORCH_LOGS"] = "-all"

import random
import re
import subprocess
import sys
import threading
import warnings
import time
from datetime import datetime
from contextlib import nullcontext
from getpass import getuser

from src.init.identity import register_assistant
from src.init.terminal import TerminalUI, interactive_terminal
from src.init.brain import VOICE_MODEL, VOICE_REFERENCE, VOICE_REFERENCE_TEXT
from src.init.voice_client import VoiceClient
from src.init.console import DebugConsole

if __name__ == "__main__":
    sys.modules["agent"] = sys.modules[__name__]


class Assistant:
    """One shared assistant; reading its identity never
    starts the model or UI."""
    name = "Arlo"
    voice: VoiceClient = None
    terminal_ui: TerminalUI
    _instance = None
    _instance_lock = threading.Lock()
    debug_console = None

    def __new__(cls):
        with cls._instance_lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance.terminal_ui = None
                instance.agent = None
                instance.shutdown_requested = threading.Event()
                instance.voice = None
                instance.debug_console = None
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
        return figlet_format(self.name, font="4max", width=128)

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

        self.voice = VoiceClient(audio_callback=(
                self.terminal_ui.update_audio_levels
                if self.terminal_ui is not None
                else None))

        self.MODEL_NAME = MODEL_NAME
        self.model_settings = {
            "openai_reasoning_effort": "none",
            "temperature": 0.2,
        }

        self.model = OllamaModel(
            self.MODEL_NAME,
            provider=OllamaProvider(base_url="http://localhost:11434/v1"),
            settings=self.model_settings)

        self.agent = Agent(
            model=self.model,
            tools=[Tool(function, sequential=True) for function in TOOLS])

        self.agent.instructions(self.current_instructions)
        self.agent.instructions(self.current_datetime_instructions)
        self.agent.instructions(self.working_directory_instructions)
        from src.init.memory.integration import memory_instructions
        self.agent.instructions(memory_instructions)

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
        return rules.current_instructions()

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
                         on_audio=None, on_speaking=None, cancel_event=None,
                         event_loop=None, attachments=None, session=None):
        """Cancel the model stream and queued speech before accepting steering."""
        import asyncio
        from src.init import brain
        from src.init.streaming import SpeechBuffer
        from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

        self._initialize_runtime()
        self.voice.audio_callback = on_audio
        self.voice.speaking_callback = on_speaking
        self.voice.begin_turn()
        cancel_event = cancel_event if cancel_event is not None else threading.Event()
        reply = []
        completed_history = None
        stream_messages = list(history)

        if attachments:
            attachments.reserve_history(history)
        model_prompt = attachments.prompt() if attachments else prompt
        attachment_tools = [attachments.toolset()] if attachments else []

        async def generate():
            nonlocal completed_history, stream_messages
            from pydantic_ai.messages import PartStartEvent, PartDeltaEvent, TextPartDelta
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
                    if chunk:
                        reply.append(chunk)
                        if on_chunk is not None:
                            on_chunk(chunk)
                        for phrase in buffer.feed(chunk):
                            self.voice.enqueue(phrase)

            result = await self.agent.run(
                model_prompt, message_history=history, toolsets=attachment_tools,
                model_settings={"temperature": brain.load_config()["temperature"]},
                event_stream_handler=stream_events)
            completed_history = result.all_messages()
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
            active_attachments.reset(attachment_token)
            self.voice.audio_callback = None
            self.voice.speaking_callback = None
            if on_speaking is not None:
                on_speaking(False)

        text = "".join(reply)
        if cancel_event.is_set():
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
        return text, completed_history

    def run_session(self):
        logger = logging.getLogger("arlo.trace")

        self._initialize_runtime()
        from pydantic_ai.messages import (
            ModelRequest, ModelResponse, TextPart, UserPromptPart)

        from src.init import brain
        from src.init.brain import (
            refresh_model_keep_alive, refresh, get_working_directory)

        from src.init.output import chunks_group
        from src.init.session_log import SessionLog
        from src.init.colors import ASSISTANT_COLOR, RESET_COLOR
        from src.init.voice import VOICE_COMMANDS, capture_voice_input
        from src.init.lang import tr

        session = SessionLog()
        refresh_model_keep_alive()

        if self.terminal_ui is None:
            from colorama import Fore
            from shutil import get_terminal_size

            lines = self.banner.rstrip("\n").splitlines()
            width = get_terminal_size().columns
            left = max(0, (width - max(map(len, lines), default=0)) // 2)
            sys.stdout.write(f"{RESET_COLOR}{Fore.LIGHTWHITE_EX}\n")
            sys.stdout.write("\n".join(" " * left + line for line in lines))
            sys.stdout.write(f"{RESET_COLOR}\n")

        version = brain.get_version()

        if self.terminal_ui is not None:
            self.terminal_ui.set_version(version)

        greeting = self.startup_greeting

        history = []
        while not self.shutdown_requested.is_set():
            prompt = self.build_user_prompt()
            if session.private:
                prompt = tr("status.private") + " " + prompt

            user_input = self.read_user_input(prompt, placeholder=greeting)
            greeting = ""

            logging.getLogger("arlo.user").info(
                "%s: %s",
                self.username,
                user_input)

            privacy_result = session.handle_command(user_input)

            if privacy_result is not None:
                continue

            if user_input.strip().casefold() not in VOICE_COMMANDS:
                session.write(self.username, user_input)

            if user_input.strip().lower() in ("quit", "exit"):
                break

            if user_input.strip().lower() in ("ref", "reload"):
                continue

            directory_result = self.directory_cmd(user_input)
            if directory_result is not None:
                session.write(self.name, directory_result)
                continue

            git_result = self.git_cmd(user_input)

            if git_result is not None:
                session.write(self.name, git_result)
                history.extend([
                    ModelRequest(parts=[UserPromptPart(user_input)]),
                    ModelResponse(parts=[TextPart(
                        f"Direct Git command result in {get_working_directory()}:\n"
                        f"{git_result}")]),
                ])
                continue

            file_content = self.print_file_cmd(user_input)
            if file_content is not None:
                self.printlns(file_content)
                session.write(self.name, file_content)
                continue

            if user_input.strip().casefold() in VOICE_COMMANDS:
                try:
                    user_input = capture_voice_input()
                except Exception as error:
                    session.write("System", str(error))
                    continue
                if not user_input:
                    session.write("System", tr("voice.transcription_failed"))
                    continue
                session.write(self.username, json.loads(user_input)[
                    "voice_text"])

            if self.terminal_ui is not None:
                self.terminal_ui.set_thinking(True)

            try:
                logging.getLogger("arlo.llm").debug(tr('agent.processing_request'))
                reply, history = self.run_desktop_turn(
                    user_input, history,
                    session=session,
                    on_audio=(self.terminal_ui.update_audio_levels
                              if self.terminal_ui is not None else None))
                if reply:
                    session.write(self.name, reply)
                if self.terminal_ui is not None:
                    self.terminal_ui.set_thinking(False)
                    self.terminal_ui.clear_audio_levels()

            except Exception as error:
                if self.terminal_ui is not None:
                    self.terminal_ui.set_thinking(False)
                cause = error.__cause__
                if cause is not None:
                    logger.error(tr('agent.trace_10_exception_caught_s'), cause)
                    session.write("System", f"{error}; Detail: {cause}"
                if cause is not None else str(error))

        session.close()

    def run(self):
        try:
            self.debug_console = DebugConsole()
            self.debug_console.start()
            self.debug_console.configure_logging()

            logging.getLogger("arlo").info(tr('agent.arlo_is_awake'))

            if interactive_terminal():
                ui = TerminalUI()
                self.terminal_ui = ui
                self.debug_console.redirect_native_streams()
                self.debug_console.redirect_streams()

                try:
                    with ui:
                        ui.set_banner(self.banner)
                        self.run_session()
                finally:
                    if self.voice is not None:
                        self.voice.close()
                        self.voice = None

                    self.debug_console.restore_streams()
                    self.debug_console.restore_native_streams()
                    self.terminal_ui = None
            else:
                self._initialize_runtime()
                try:
                    self.run_session()
                finally:
                    if self.voice is not None:
                        self.voice.close()
                        self.voice = None

        except (EOFError, KeyboardInterrupt):
            pass


register_assistant(Assistant)


def main():
    Assistant().run()


if __name__ == "__main__":
    main()
