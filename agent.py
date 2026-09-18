#! /usr/bin/env python3
# type: ignore
"""Arlo's main entry to the whole brain, no pun intended
see how Arlo works and engineers from here"""
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
from contextlib import nullcontext
from getpass import getuser

from src.init.identity import register_assistant
from src.init.terminal import TerminalUI, interactive_terminal
from src.init.brain import VOICE_MODEL, VOICE_REFERENCE, VOICE_REFERENCE_TEXT
from src.init.voice_service import VoiceService

if __name__ == "__main__":
    sys.modules["agent"] = sys.modules[__name__]


class Assistant:
    """One shared assistant; reading its identity never
    starts the model or UI."""
    name = "Arlo"
    voice: VoiceService = None
    terminal_ui: TerminalUI
    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        with cls._instance_lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance.terminal_ui = None
                instance.agent = None
                instance.voice = None
                instance.username = getuser().capitalize()
                instance.typewriter_delay_seconds = float(
                    os.environ.get("TYPEWRITER_DELAY", "0"))
                cls._instance = instance
            return cls._instance

    @property
    def startup_greeting(self) -> str:
        greetings = (
            f"Hola, {self.username}. ¿Qué quieres hacer?",
            f"Hola, {self.username}. ¿En qué te ayudo?",
            f"Estoy listo, {self.username}. ¿Qué hacemos?",
            f"¿Qué necesitas hoy, {self.username}?",
            f"Todo listo, {self.username}. ¿Por dónde empezamos?",
            f"{self.name} preparado. Escribe lo que necesites.",
        )
        return random.choice(greetings)

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

        logging.getLogger().setLevel(logging.WARNING)
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

        self.voice = VoiceService(
            model_path=VOICE_MODEL,
            voice_reference=VOICE_REFERENCE,
            reference_text=VOICE_REFERENCE_TEXT,
            speed=1.0,
            audio_callback=self.terminal_ui.update_audio_levels
            if self.terminal_ui is not None else None)

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
        self.agent.instructions(self.working_directory_instructions)


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
        """Consume the LLM stream and queue complete phrases for speech."""
        buffer = ""
        reply = []
        for chunk in chunks:
            if not chunk:
                continue

            reply.append(chunk)
            buffer += chunk
            while True:
                match = re.search(r"(?<=[.!?,;:\n])\s+", buffer)
                if match is not None:
                    end = match.end()
                elif len(buffer) >= 50:
                    split = buffer.rfind(" ", 0, 50)
                    end = split + 1 if split > 20 else 50
                else:
                    break
                phrase = buffer[:end].strip()
                buffer = buffer[end:]
                if phrase:
                    self.voice.enqueue(phrase)

        if buffer.strip():
            self.voice.enqueue(buffer.strip())

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
                print(content)
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

    def run_session(self):
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
        while True:
            prompt = self.build_user_prompt()
            if session.private:
                prompt = "[PRIVATE] " + prompt

            user_input = self.read_user_input(prompt, placeholder=greeting)
            greeting = ""

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
                    session.write("System", "A voice transcription "
                                            "was impossible to obtain.")
                    continue
                session.write(self.username, json.loads(user_input)[
                    "voice_text"])

            if self.terminal_ui is not None:
                self.terminal_ui.set_thinking(True)

            try:
                result = self.agent.run_sync(
                    user_input,
                    message_history=history,
                    model_settings={"temperature": brain.load_config()["temperature"]})

                reply = result.output
                if self.terminal_ui is not None:
                    self.terminal_ui.set_thinking(False)

                if reply:
                    session.write(self.name, reply)
                    self.voice.enqueue(reply)

                self.voice.wait_until_done()

                if self.terminal_ui is not None:
                    self.terminal_ui.clear_audio_levels()

                history = result.all_messages()

            except Exception as error:
                if self.terminal_ui is not None:
                    self.terminal_ui.set_thinking(False)
                cause = error.__cause__
                if cause is not None:
                    session.write("System", f"{error}; Detail: {cause}"
                if cause is not None else str(error))

    def run(self):
        try:
            if interactive_terminal():
                with TerminalUI() as ui:
                    self.terminal_ui = ui
                    ui.set_banner(self.banner)
                    try:
                        self.run_session()
                    finally:
                        self.terminal_ui = None
            else:
                self._initialize_runtime()
                self.run_session()

        except (EOFError, KeyboardInterrupt):
            pass


register_assistant(Assistant)


def main():
    Assistant().run()


if __name__ == "__main__":
    main()
