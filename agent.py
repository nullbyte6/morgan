#type: ignore
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
from getpass import getuser

from src.init.identity import register_assistant

if __name__ == "__main__":
    sys.modules["agent"] = sys.modules[__name__]

class Assistant:
    """One shared assistant; reading its identity never
    starts the model or UI."""
    name = "Nora"
    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        with cls._instance_lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance.terminal_ui = None
                instance.agent = None
                instance.username = getuser().capitalize()
                instance.typewriter_delay_seconds = float(
                    os.environ.get("NORA_TYPEWRITER_DELAY", "0"))
                cls._instance = instance
            return cls._instance

    @property
    def startup_greetings(self):
        return (
            f"Hola, {self.username}. {self.name} lista para empezar.",
            f"Ya estoy aquí, {self.username}. Vamos a ello.",
            "Todo listo. Dime qué necesitas y me pongo a ello.",
            "Hola de nuevo. Lista para echarte una mano.",
            f"{self.name} al habla. Cuando quieras, empezamos.",
            f"¡Buenas, {self.username}! Manos a la obra.",
        )

    @property
    def banner(self):
        from pyfiglet import figlet_format
        return figlet_format(self.name, font="4max", width=128)

    def _initialize_runtime(self):
        if self.agent is not None:
            return
        os.environ["PYDANTIC_AI_NO_BANNER"] = "1"
        os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
        from colorama import just_fix_windows_console
        from pydantic_ai import Agent, Tool
        from pydantic_ai.models.ollama import OllamaModel
        from pydantic_ai.providers.ollama import OllamaProvider
        from src.init.brain import MODEL_NAME
        from src.init.tools import TOOLS

        self.MODEL_NAME = MODEL_NAME
        just_fix_windows_console()
        self.model_settings = {
            "openai_reasoning_effort": "none",
            "temperature": 0.2,
        }
        self.model = OllamaModel(
            self.MODEL_NAME,
            provider=OllamaProvider(base_url="http://localhost:11434/v1"),
            settings=self.model_settings,
        )
        self.agent = Agent(
            model=self.model,
            tools=[Tool(function, sequential=True) for function in TOOLS],
        )
        self.agent.instructions(self.current_instructions)
        self.agent.instructions(self.working_directory_instructions)

    def stream(self, chunks, session=None) -> None:
        """Shows remaining fragments immediately, animation delay is optional"""
        from src.init.output import chunks_group
        from src.init.spin import ASSISTANT_COLOR, RESET_COLOR

        sys.stdout.write(f"{ASSISTANT_COLOR}")
        displayed = []
        response_prefix = self.terminal_ui.output_snapshot() if self.terminal_ui is not None else None
        def capture(source):
            for chunk in source:
                displayed.append(chunk)
                yield chunk

        try:
            source = capture([chunks] if isinstance(chunks, str) else chunks)
            for chunk in (
            source if self.terminal_ui is not None else chunks_group(source, color=True)):
                if self.terminal_ui is not None:
                    self.terminal_ui.update_response(response_prefix,
                                                "".join(chunks_group(
                                                    ["".join(displayed)], color=True)))
                elif self.typewriter_delay_seconds:
                    for character in chunk:
                        sys.stdout.write(character)
                        sys.stdout.flush()
                        time.sleep(self.typewriter_delay_seconds)
                else:
                    sys.stdout.write(chunk)
                    sys.stdout.flush()
        finally:
            sys.stdout.write(f"{RESET_COLOR}\n")
            sys.stdout.flush()
            if session is not None:
                session.write(self.name, "".join(displayed))

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

    def application_cmd(self, command: str) -> str | None:
        """Open explicit app requests without delegating routing to the LLM."""
        match = re.fullmatch(
            r"(?:abre|abrir|ejecuta|inicia|lanza|open|launch|run)\s+(.+)",
            command.strip(), flags=re.IGNORECASE)
        if match is None:
            return None
        target = match.group(1).strip().strip('"').strip("'")
        if not target:
            return None
        lowered = target.casefold()
        if (lowered.startswith(("http://", "https://", "www."))
                or re.search(r"\s+(?:y|and)\s+", lowered)
                or re.search(r"\b[\w.-]+\.(?:com|es|org|net|io)\b", lowered)
                or any(word in lowered for word in (
                    "directorio", "carpeta", "folder", "directory", "archivo",
                    "fichero", "file", "navegador", "browser", "repositorio",
                    "repository"))):
            return None
        target = re.sub(
            r"^(?:la\s+|el\s+)?(?:app|aplicaci[oó]n|application|programa|program)\s+(?:de\s+)?",
            "", target, flags=re.IGNORECASE,
        ).strip()
        target = re.sub(r"\s+(?:por\s+favor|please)$", "", target,
                        flags=re.IGNORECASE).strip()
        target = re.sub(r"^(?:el|la)\s+", "", target,
                        flags=re.IGNORECASE).strip()
        if not target:
            return None
        from src.init.brain import open_application

        result = open_application(target)
        if self._response_language(command) == "español":
            translations = (
                ("Opened application:", "Aplicación abierta:"),
                ("Application not found:", "No se encontró la aplicación:"),
                ("Application path not found or is not an executable file:",
                 "La ruta no existe o no es un ejecutable:"),
                ("Error opening application path:", "Error al abrir la ruta:"),
            )
            for source, translated in translations:
                if result.startswith(source):
                    return translated + result[len(source):]
        return result

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

    def build_user_prompt(self) -> str:
        """Show the current location and live Git branch, including unborn branches."""
        from src.init import brain
        from src.init.brain import get_working_directory

        if not brain.should_show_working_directory():
            return ">> "
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

    def read_user_input(self, prompt: str | None = None) -> str:
        """Read input with a normal prompt and the user's typed text in green."""
        from src.init.spin import RESET_COLOR, USER_COLOR

        if prompt is None:
            prompt = self.build_user_prompt()
        if self.terminal_ui is not None:
            return self.terminal_ui.read_input(prompt)
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

    @staticmethod
    def _response_language(text: str) -> str | None:
        """Infer a lightweight response-language hint from the latest text.

        Tool output and previous turns can be in another language.  A small
        local vocabulary is enough to disambiguate the common Spanish/English
        commands without adding a network dependency or changing the user's
        message semantics.
        """
        words = set(re.findall(r"[a-záéíóúüñ]+", text.casefold()))
        spanish = {"abre", "abrir", "dime", "cuál", "cual", "qué", "que",
                   "tienes", "puedes", "quiero", "necesito", "ejecuta",
                   "reproduce", "reproducir", "pausa", "busca", "cómo",
                   "como", "por", "para", "con", "en", "el", "la", "los",
                   "las", "una", "un", "mi", "me", "de", "del", "dónde",
                   "donde"}
        english = {"open", "tell", "what", "which", "can", "please", "run",
                   "play", "pause", "search", "how", "where", "my", "the",
                   "a", "an", "in", "to", "for", "with"}
        spanish_score = len(words & spanish)
        english_score = len(words & english)
        if any(character in text for character in "áéíóúüñ¿¡"):
            spanish_score += 2
        if spanish_score > english_score and spanish_score >= 1:
            return "español"
        if english_score > spanish_score and english_score >= 1:
            return "inglés"
        return None

    def _localized_request(self, user_input: str) -> str:
        language = self._response_language(user_input)
        if language is None:
            return user_input
        return (f"[IDIOMA DE RESPUESTA OBLIGATORIO: responde exclusivamente en {language}. "
                "No cambies de idioma por el resultado de una herramienta ni por el historial.]\n"
                + user_input)

    def run_session(self):
        self._initialize_runtime()
        from pydantic_ai.messages import (
            ModelRequest, ModelResponse, TextPart, UserPromptPart,
        )
        from src.init import brain
        from src.init.brain import (
            refresh_model_keep_alive, refresh, get_working_directory,
        )
        from src.init.output import chunks_group
        from src.init.session_log import SessionLog
        from src.init.spin import ASSISTANT_COLOR, RESET_COLOR, Spinner
        from src.init.voice import VOICE_COMMANDS, capture_voice_input

        session = SessionLog()
        refresh_model_keep_alive()
        if self.terminal_ui is not None:
            self.terminal_ui.set_banner(self.banner)
        else:
            from colorama import Fore
            from shutil import get_terminal_size

            lines = self.banner.rstrip("\n").splitlines()
            width = get_terminal_size().columns
            left = max(0, (width - max(map(len, lines), default=0)) // 2)
            sys.stdout.write(f"{RESET_COLOR}{Fore.LIGHTWHITE_EX}\n")
            sys.stdout.write("\n".join(" " * left + line for line in lines))
            sys.stdout.write(f"{RESET_COLOR}\n")
        self.stream(brain.get_version())
        self.stream([random.choice(self.startup_greetings)], session=session)
        history = []
        while True:
            prompt = self.build_user_prompt()
            if session.private:
                prompt = "[PRIVATE] " + prompt
            user_input = self.read_user_input(prompt)
            privacy_result = session.handle_command(user_input)
            if privacy_result is not None:
                self.stream(privacy_result)
                continue
            if user_input.strip().casefold() not in VOICE_COMMANDS:
                session.write(self.username, user_input)
            if user_input.strip().lower() in ("quit", "exit"):
                break

            if user_input.strip().lower() in ("ref", "reload"):
                self.stream([refresh()], session=session)
                continue

            directory_result = self.directory_cmd(user_input)
            if directory_result is not None:
                self.stream(directory_result)
                session.write(self.name, directory_result)
                continue
            application_result = self.application_cmd(user_input)
            if application_result is not None:
                self.stream(application_result, session=session)
                continue
            git_result = self.git_cmd(user_input)
            if git_result is not None:
                self.stream(f"{ASSISTANT_COLOR}{git_result}{RESET_COLOR}")
                session.write(self.name, git_result)
                history.extend([
                    ModelRequest(parts=[UserPromptPart(user_input)]),
                    ModelResponse(parts=[TextPart(
                        f"Direct Git command result in {get_working_directory()}:\n"
                        f"{git_result}")]),
                ])
                continue
            if user_input.strip().casefold() in VOICE_COMMANDS:
                try:
                    user_input = capture_voice_input()
                except Exception as error:
                    self.stream(f"VOICE ERROR: {error}")
                    session.write("System", str(error))
                    continue
                if not user_input:
                    session.write("System", "A voice transcription "
                                            "was impossible to obtain.")
                    continue
                session.write(self.username, json.loads(user_input)[
                    "voice_text"])
            spinner = Spinner()
            spinner.start()
            try:
                with self.agent.run_stream_sync(
                        self._localized_request(user_input), message_history=history,
                        model_settings={"temperature": brain.load_config()[
                            "temperature"]}) as result:
                    spinner.stop()
                    self.stream(result.stream_text(delta=True, debounce_by=None),
                           session=session)
                    history = result.all_messages()
                    for message in history:
                        if isinstance(message, ModelResponse):
                            for part in message.parts:
                                if isinstance(part, TextPart):
                                    part.content = "".join(
                                        chunks_group([part.content]))
                    refresh_model_keep_alive()
            except Exception as error:
                spinner.stop()
                self.stream(f"ERROR: {error}")
                cause = error.__cause__
                if cause is not None:
                    self.stream(f"Detail: {cause}")
                session.write("System", f"{error}; Detail: {cause}"
                if cause is not None else str(error))

    def run(self):
        from src.init.terminal import TerminalUI, interactive_terminal

        self._initialize_runtime()
        try:
            if interactive_terminal():
                with TerminalUI() as ui:
                    self.terminal_ui = ui
                    try:
                        self.run_session()
                    finally:
                        self.terminal_ui = None
            else:
                self.run_session()
        except (EOFError, KeyboardInterrupt):
            pass


register_assistant(Assistant)

def main():
    Assistant().run()


if __name__ == "__main__":
    main()
