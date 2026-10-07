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
import logging
import json
import os
import re
import subprocess
import sys
import threading
import weakref
from contextlib import nullcontext
from datetime import datetime
from getpass import getuser

from pydantic_ai import Agent, Tool

from src.init import latency
from src.init.config import load_config
from src.init.identity import get_assistant_gender_instruction, get_assistant_name
from src.init.voice_client import VoiceClient
from src.platforms import current_platform

VOICE_STREAMING = os.environ.get("MORGAN_VOICE_STREAMING", "1") != "0"
DIRECT_STREAM_CHARACTERS = 900
DIRECT_STREAM_LINES = 18


def _tool_payload(value, tool_names):
    try:
        payload = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None
    if (not isinstance(payload, dict)
            or set(payload) != {"name", "arguments"}
            or payload["name"] not in tool_names
            or not isinstance(payload["arguments"], dict)):
        return None
    return payload["name"], payload["arguments"]


def extract_text_tool_call(text, tool_names):
    fenced = re.compile(
        r"```json\s*\n(?P<body>.*?)\n```", re.DOTALL | re.IGNORECASE)
    for match in fenced.finditer(text):
        call = _tool_payload(match.group("body").strip(), tool_names)
        if call is not None:
            visible = (text[:match.start()] + text[match.end():]).strip()
            return visible, call
    stripped = text.strip()
    call = _tool_payload(stripped, tool_names)
    return ("", call) if call is not None else (text, None)


class AssistantTextStream:
    def __init__(self, tool_names, emit):
        self.tool_names = tool_names
        self.emit = emit
        self.visible = []
        self.prefix = ""
        self.candidate = None
        self.at_line_start = True

    def _output(self, text):
        if text:
            self.visible.append(text)
            self.emit(text)

    def feed(self, text):
        output = []
        for character in text:
            if self.candidate is not None:
                self.candidate += character
                continue
            if self.at_line_start:
                self.prefix += character
                stripped = self.prefix.lstrip()
                candidate_prefix = stripped.rstrip("\r\n").casefold()
                if stripped.startswith("{"):
                    self.candidate = self.prefix
                    self.prefix = ""
                    self.at_line_start = False
                elif "```json".startswith(candidate_prefix):
                    if candidate_prefix == "```json" and character == "\n":
                        self.candidate = self.prefix
                        self.prefix = ""
                        self.at_line_start = False
                elif stripped or character == "\n":
                    output.append(self.prefix)
                    self.at_line_start = character == "\n"
                    self.prefix = ""
                continue
            output.append(character)
            if character == "\n":
                self.at_line_start = True
        self._output("".join(output))

    def finish(self):
        pending = self.candidate if self.candidate is not None else self.prefix
        visible, call = extract_text_tool_call(pending, self.tool_names)
        self._output(visible)
        self.candidate = None
        self.prefix = ""
        return "".join(self.visible), call


# noinspection PyBroadException
class Assistant:
    """One shared assistant; reading its identity never
    starts the model or UI."""
    @property
    def name(self) -> str:
        return get_assistant_name()

    voice: VoiceClient = None
    speech_enabled: bool = True
    voice_service_required: bool = True
    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        with cls._instance_lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance.agent = None
                instance.provider = None
                instance.shutdown_requested = threading.Event()
                instance._active_cancellation_token = None
                instance._active_task_controller = None
                instance.voice = None
                instance._reload_lock = threading.Lock()
                instance._speech_lock = threading.Lock()
                instance._speech_owner = None
                instance._loop_models = weakref.WeakKeyDictionary()
                instance._loop_models_lock = threading.Lock()
                instance.username = getuser().capitalize()
                cls._instance = instance
            return cls._instance

    @staticmethod
    def _last_spoken_language() -> str | None:
        from src.init.lang import detect_language
        from src.init.memory.integration import configured_service

        try:
            service = configured_service()
            for text in service.recent_user_messages() if service is not None else ():
                language = detect_language(text)
                if language:
                    return language
        except Exception:
            logging.getLogger("assistant.memory").exception("The last spoken language could not be read for the greeting")
        return None

    def generate_greeting(self) -> str:
        """Ask the main model for a short startup greeting in the language the user last spoke, else the interface language."""
        import urllib.request
        from src.init.brain import OLLAMA_KEEP_ALIVE
        from src.init.health import record_model_load
        from src.init.lang import LANGUAGE_NAMES, get_language

        language = LANGUAGE_NAMES.get(self._last_spoken_language() or get_language(), "English")
        try:
            from src.init.nova.tools import agenda_brief
            agenda = agenda_brief()
        except Exception:
            logging.getLogger("assistant.nova").exception("Today's agenda could not be read for the greeting")
            agenda = ""
        if agenda:
            request_text = (f"Write a short, natural greeting of at most thirty words in {language} for the user, "
                            f"{self.username}, that briefly mentions today's agenda from Nova, the user's agenda: "
                            f"{agenda}. Summarise it, for example how many reminders there are and the time of "
                            "the next event, instead of listing everything. ")
        else:
            request_text = (f"Write one short, natural greeting of at most twelve words in {language} for the user, "
                            f"{self.username}, offering your help. ")
        prompt = (f"You are {self.name}, a personal desktop assistant that has just started. "
                  f"{request_text}Start with a simple salutation in {language} and the user's name, like \"Hi {self.username}, ...\", "
                  "and do not introduce yourself or mention your own name, since the user already knows you. "
                  f"{get_assistant_gender_instruction()} Use it consistently. Use a "
                  f"{load_config()['personality']['tone']} tone and vary the wording. "
                  "Reply with the greeting only, without quotes, emojis or Markdown.")
        payload = json.dumps({
            "model": self.MODEL_NAME, "prompt": prompt, "stream": False, "think": False,
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "options": {"temperature": 1.0, "num_predict": 120 if agenda else 60},
        }).encode("utf-8")
        request = urllib.request.Request(
            "http://127.0.0.1:11434/api/generate", data=payload,
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                reply = json.loads(response.read())
            record_model_load(self.MODEL_NAME, reply)
            text = reply["response"]
        except (OSError, ValueError, KeyError, TypeError):
            logging.getLogger("assistant.model").exception("Startup greeting could not be generated")
            return ""
        lines = (line.strip().strip("\"'“”«»*").strip() for line in str(text).splitlines())
        return next((line for line in lines if line), "")[:300]


    def _ensure_services(self):
        platform = current_platform()
        name: str = load_config()["assistant"]["name"]
        launchers = platform.service_launchers(name)
        if not launchers:
            return
        import socket
        import sys
        from pathlib import Path
        from src.init.lang import tr
        from src.init.paths import PROJECT_ROOT

        def services_ready():
            for port in (11434, 18765) if self.voice_service_required else (11434,):
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=1):
                        pass
                except OSError:
                    return False
            return True

        def align_ollama_context():
            from src.init.ollama_service import (missing_gpu_groups, ollama_ready, restart_ollama,
                                                 server_context_length)
            configured = load_config()["context_length"]
            if ollama_ready() and (server_context_length() != configured or missing_gpu_groups()):
                restart_ollama(configured)

        try:
            align_ollama_context()
        except Exception:
            logging.getLogger("assistant.services").exception(
                "Ollama could not be restarted with the configured context length")
        if services_ready():
            return
        directories = [PROJECT_ROOT / "scripts"]
        if getattr(sys, "frozen", False):
            directories.append(Path(sys.executable).resolve().parent / "scripts")

        def registry_value(variable):
            value = platform.user_environment(variable)
            return os.path.expandvars(value) if value else None

        install = os.environ.get(name.upper()) or registry_value(name.upper())
        if install:
            directories.append(Path(install) / "scripts")
        home = os.environ.get(f"{name.upper()}_HOME") or registry_value(f"{name.upper()}_HOME")
        if home:
            directories[:0] = [Path(home), Path(home) / "scripts"]
        candidates = [directory / launcher for directory in directories for launcher in launchers]
        services = next((path for path in candidates if path.is_file()), None)
        if services is None:
            raise RuntimeError(tr("startup.services_missing"))
        command = platform.service_command(services, self.voice_service_required)
        bundle = Path(sys._MEIPASS).resolve() if getattr(sys, "frozen", False) else None
        libraries = platform.unbundled_libraries(bundle) if bundle else nullcontext()
        try:
            with libraries:
                environment = os.environ.copy()
                if bundle:
                    environment["PATH"] = os.pathsep.join(
                        entry for entry in environment.get("PATH", "").split(os.pathsep)
                        if not Path(os.path.expandvars(entry)).resolve().is_relative_to(bundle))
                    environment.pop("PYTHONHOME", None)
                process = subprocess.Popen(
                    command, cwd=str(services.parent.parent), env=environment,
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, errors="replace", creationflags=platform.no_window_flags)
            try:
                output, _ = process.communicate(timeout=900)
            except subprocess.TimeoutExpired as error:
                process.kill()
                process.communicate()
                raise RuntimeError(tr("startup.services_timeout")) from error
        except OSError as error:
            raise RuntimeError(tr("startup.services_failed", error=str(error))) from error
        if process.returncode:
            raise RuntimeError(tr("startup.services_failed", error=output.strip()[-2000:]))
        if not services_ready():
            raise RuntimeError(tr("startup.services_not_ready"))
        logging.getLogger("assistant.services").info(output.rstrip())

    @staticmethod
    def _preload_runtime():
        try:
            import pydantic_ai.models.ollama
            import src.init.tools
        except Exception:
            logging.getLogger("assistant.startup").exception("Runtime modules could not be preloaded")

    def _initialize_runtime(self):
        if self.agent is not None:
            return
        os.environ["PYDANTIC_AI_NO_BANNER"] = "1"
        os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
        preload = threading.Thread(target=self._preload_runtime, name="runtime-preload", daemon=True)
        preload.start()
        self._ensure_services()
        preload.join()
        from pydantic_ai import Agent, Tool

        for logger_name in (
                "httpx",
                "httpcore",
                "httpcore2",
                "openai",
                "pydantic_ai"):
            logger = logging.getLogger(logger_name)
            logger.setLevel(logging.CRITICAL)
            logger.propagate = False

        from src.init.brain import get_selected_model
        from src.init.tools import TOOLS

        if self.voice is None:
            self.voice = VoiceClient()

        self.selected_model = get_selected_model()
        self.MODEL_NAME = self.selected_model
        self.model_settings = {
            "thinking": False,
            "openai_reasoning_effort": "none",
            "temperature": 0.2,
        }

        self.provider = self._new_provider()
        self.model = self._main_model()

        self.agent = Agent(
            model=self.model,
            tools=[Tool(function, sequential=True) for function in TOOLS])

        self.agent.instructions(self.current_instructions)
        self.agent.instructions(self.wd_instructions)
        from src.init.memory.integration import memory_instructions
        self.agent.instructions(memory_instructions)
        self.agent.instructions(
            "When the user explicitly requests a flowchart, diagram, "
            "workflow, decision tree, or process visualization, call "
            "render_flowchart with newly supplied nodes and edges. "
            "It does not require an existing diagram. Do not claim "
            "this capability is unavailable.")
        self.agent.instructions(self.current_datetime_instructions)

    @staticmethod
    def _new_provider():
        from pydantic_ai.models import DEFAULT_HTTP_TIMEOUT, get_user_agent
        from pydantic_ai.providers.ollama import OllamaProvider
        from src.init.task_trace import trace_provider_request
        import httpx2

        http_client = httpx2.AsyncClient(
            timeout=httpx2.Timeout(timeout=DEFAULT_HTTP_TIMEOUT, connect=5),
            headers={"User-Agent": get_user_agent()}, event_hooks={"request": [trace_provider_request]})
        return OllamaProvider(base_url="http://127.0.0.1:11434/v1", http_client=http_client)

    def _main_model(self, provider=None, name=None):
        from pydantic_ai.models.ollama import OllamaModel

        return OllamaModel(
            name or self.MODEL_NAME, provider=provider or self.provider,
            profile={"openai_chat_supports_multiple_system_messages": False,
                     "openai_chat_supports_max_completion_tokens": False,
                     "openai_supports_tool_choice_required": False},
            settings=self.model_settings)

    def _loop_runtime(self, event_loop):
        """Return this loop's own HTTP client handles for the shared Ollama model."""
        if event_loop is None:
            return {"provider": self.provider, "models": {}}
        with self._loop_models_lock:
            runtime = self._loop_models.get(event_loop)
            if runtime is None:
                runtime = {"provider": self._new_provider(), "models": {}}
                self._loop_models[event_loop] = runtime
            return runtime

    def release_event_loop(self, event_loop):
        with self._loop_models_lock:
            runtime = self._loop_models.pop(event_loop, None)
        if runtime is None or event_loop.is_closed():
            return
        try:
            event_loop.run_until_complete(runtime["provider"].client.close())
        except Exception:
            logging.getLogger("assistant.model").exception("Unable to close a session HTTP client")

    def _loop_model(self, event_loop, name, factory):
        runtime = self._loop_runtime(event_loop)
        model = runtime["models"].get(name)
        if model is None:
            model = factory(runtime["provider"])
            runtime["models"][name] = model
        return model

    def _session_main_model(self, event_loop):
        if event_loop is None:
            return self.model
        return self._loop_model(event_loop, ("main", self.MODEL_NAME), self._main_model)

    def acquire_speech(self, owner) -> bool:
        """Give text-to-speech to one session at a time without waiting."""
        with self._speech_lock:
            if self._speech_owner is None or self._speech_owner is owner:
                self._speech_owner = owner
                return True
            return False

    def speech_unowned(self) -> bool:
        with self._speech_lock:
            return self._speech_owner is None

    def release_speech(self, owner) -> None:
        with self._speech_lock:
            if self._speech_owner is owner:
                self._speech_owner = None

    def reload_source(self) -> str:
        """Reload source modules and rebuild the model and tools for next turn."""
        with self._reload_lock:
            from src.init.hot_reload import reload_project_modules

            reloaded, errors = reload_project_modules()
            with self._loop_models_lock:
                for runtime in self._loop_models.values():
                    runtime["models"].clear()

            if self.agent is not None:
                from src.init.brain import get_selected_model
                from src.init.tools import TOOLS

                self.selected_model = get_selected_model()
                self.MODEL_NAME = self.selected_model
                self.model = self._main_model()
                self.agent = Agent(
                    model=self.model,
                    tools=[Tool(function, sequential=True)
                           for function in TOOLS])
                self.agent.instructions(self.current_instructions)
                self.agent.instructions(self.wd_instructions)
                from src.init.memory.integration import memory_instructions
                self.agent.instructions(memory_instructions)

                self.agent.instructions(
                    "When the user explicitly requests a flowchart, diagram, "
                    "workflow, decision tree, or process visualization, call "
                    "render_flowchart with newly supplied nodes and edges. "
                    "It does not require an existing diagram. Do not claim "
                    "this capability is unavailable.")
                self.agent.instructions(self.current_datetime_instructions)

            summary = f"Reloaded {len(reloaded)} source modules"
            if errors:
                summary += "; failures: " + " | ".join(errors)
            else:
                summary += "; the refreshed tools will be used on the next turn."
            return summary

    def speak(self, chunks) -> str:
        """Stream LLM output invisibly and feed complete phrases to TTS."""
        from src.init.streaming import SpeechBuffer
        self.voice.begin_turn()
        buffer = SpeechBuffer()
        reply = []
        for chunk in chunks:
            if not chunk:
                continue
            reply.append(chunk)
            for phrase in buffer.feed(chunk):
                self.voice.enqueue(phrase)
        for phrase in buffer.finish():
            self.voice.enqueue(phrase)
        return "".join(reply)

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
                creationflags=current_platform().no_window_flags,
            )
            if result.returncode == 0:
                branch = result.stdout.strip()
            elif result.returncode == 1:
                result = subprocess.run(
                    ["git", "-C", directory, "rev-parse", "--short", "HEAD"],
                    capture_output=True, text=True, errors="replace", timeout=2,
                    creationflags=current_platform().no_window_flags,
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

        sys.stdout.write(f"{RESET_COLOR}{prompt}{USER_COLOR}")
        sys.stdout.flush()

        try:
            return input()
        finally:
            sys.stdout.write(RESET_COLOR)
            sys.stdout.flush()

    def current_instructions(self) -> str:
        from src.init import rules
        from src.init.brain import is_cloud_model
        cloud_notice = (
            "\nThe current main model runs on Ollama Cloud, not on this computer: "
            "never claim that this conversation is processed 100% locally."
            if is_cloud_model(self.MODEL_NAME) else "")
        return (rules.current_instructions() + cloud_notice
                + "\nApplication execution: call the native open_application tool "
                "for requested apps. Writing an action JSON or describing a call "
                "does not execute it. Only report an app as open when its tool "
                "result has opened=true. If launch_requested=true but opened=false, "
                "explain that the launch could not be confirmed and do not repeat it. "
                "Conversation messages can contain local artifact links replacing large "
                "tool results. Use read_file on a linked artifact when its raw "
                "contents are needed for the current reasoning.")

    def wd_instructions(self) -> str:
        from src.init.brain import get_working_directory
        from src.init.paths import PROJECT_ROOT

        return (
            f"{self.name} project root: {PROJECT_ROOT}\n"
            f"Current user working directory: {get_working_directory()}\n"
            "These are separate locations. "
            f"When the user refers to your code, {self.name}'s code, your source, "
            "your project, or asks you to inspect or modify yourself, use the "
            "self-code tools and resolve source paths relative to the project root. "
            "For ordinary user file and project operations, use the current working "
            "directory unless the user provides an explicit path. "
            "Never assume the current working directory is the project root."
        )

    def current_datetime_instructions(self) -> str:
        """Provide the actual local date and time on every model run."""
        now = datetime.now().astimezone()

        return (
            f"Current local date and time: {now.isoformat(timespec='minutes')}\n"
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

    def run(
            self,
            prompt: str,
            history: list,
            on_chunk=None,
            on_audio=None,
            on_speaking=None,
            on_subtitle=None,
            on_phase=None,
            cancel_event=None,
            event_loop=None,
            attachments=None,
            session=None, *,
            speech_enabled: bool = True, task_title: str = "", on_activity=None,
            on_surface=None, on_task_title=None, resume_task_id: str = "",
            acquire_speech=None):
        """Cancel the model stream and queued speech before accepting steering."""
        import asyncio
        from src.init import brain
        from src.init.streaming import ResponseDelivery
        from pydantic_ai import CancellationToken
        from pydantic_ai.exceptions import RunCancelled
        from pydantic_ai.messages import (ModelRequest, ModelResponse, TextPart,
                                          UserPromptPart)
        from src.init.session_log import SessionContext
        from src.init.config import HOME_PATH
        import uuid

        task_context = (session.context if session is not None else
                        SessionContext(uuid.uuid4().hex, HOME_PATH / ".log"))
        task_context.task_state = None
        if session is None:
            self.task_state = None
        directory_command = re.fullmatch(r"cd(?:\s+(.*))?", prompt.strip(), re.IGNORECASE)
        if directory_command is not None and attachments is None:
            if cancel_event is not None and cancel_event.is_set():
                return "", history
            path = directory_command.group(1) or ""
            if path.casefold().startswith("/d "):
                path = path[3:].strip()
            output = brain.change_directory(path)
            if on_chunk is not None:
                on_chunk(output)
            return output, [*history, ModelRequest(parts=[UserPromptPart(prompt)]),
                            ModelResponse(parts=[TextPart(output)])]

        self._initialize_runtime()

        owns_speech = False

        def claim_speech():
            nonlocal owns_speech
            if (not owns_speech and speech_enabled
                    and (acquire_speech is None or acquire_speech())):
                self.voice.audio_callback = on_audio
                self.voice.speaking_callback = on_speaking
                self.voice.subtitle_callback = on_subtitle
                self.voice.begin_turn(language_context=prompt)
                owns_speech = True
            return owns_speech

        cancel_event = cancel_event if cancel_event is not None else threading.Event()
        cancellation_token = CancellationToken()
        task_context.cancellation_token = cancellation_token
        if session is None:
            self._active_cancellation_token = cancellation_token
        reply = []
        completed_history = None
        execution_started = False
        stream_messages = list(history)

        if attachments:
            attachments.reserve_history(history)
        turn_model_settings = {
            **self.model_settings,
            "temperature": brain.load_config()["temperature"],
        }

        model_prompt = attachments.prompt() if attachments else prompt
        session_model = self._session_main_model(event_loop)
        attachment_tools = [attachments.toolset()] if attachments else []
        from src.init.task_control import (ExecutionControl, TaskEscalate, TaskModelRetry,
                                           TaskOutputReady, TaskStopped)
        previous =(getattr(task_context, "task_controller", None) if session is not None
                    else getattr(task_context, "task_controller", None) or self._active_task_controller)
        while previous is not None and previous.state.status in {"complete", "cancelled"}:
            previous = previous.pending_task
        pending_task = previous if (previous is not None and previous.state.status in {
            "interrupted", "waiting", "blocked", "limit_reached"}
            and (session is None or previous.context.session_id == task_context.session_id)) else None
        controller = ExecutionControl(prompt, task_context, cancel_event, pending_task=pending_task)
        task_context.task_controller = pending_task
        if session is None:
            self._active_task_controller = pending_task

        def publish_task_state(state):
            task_context.task_state = state
            if session is None:
                self.task_state = state

        from src.init.config import load_config
        request_config = load_config()
        from src.init.attachments import ollama_capabilities
        active_model = session_model.model_name
        _, provider_context = ollama_capabilities(active_model)
        operational_context = (provider_context if brain.is_cloud_model(active_model)
                               else request_config["context_length"])
        controller.request_configuration = {
            "operational_context_tokens": operational_context,
            "provider_context_tokens": provider_context,
            "effective_context_tokens": min(operational_context, provider_context),
            "configured_model": self.MODEL_NAME,
            "source": "minimum_of_dev_configuration_and_ollama_show_or_ps; provider_fallback_4096"}
        controller.task_title = task_title
        controller.on_action = on_phase
        escalation_name = brain.get_coding_model()
        controller.escalation_enabled = escalation_name != active_model

        def escalation_model():
            if event_loop is None:
                return self._main_model(name=escalation_name)
            return self._loop_model(event_loop, ("escalation", escalation_name),
                                    lambda provider: self._main_model(provider, escalation_name))

        def promoted(supervised):
            task_context.task_controller = supervised
            if session is None:
                self._active_task_controller = supervised
            publish_task_state(supervised.state)

        controller.on_promote = promoted

        def publish_task_activity(activity):
            publish_task_state(controller.state)
            if on_activity is not None:
                on_activity(activity)

        controller.on_activity = publish_task_activity
        controller.on_task_title = on_task_title

        async def generate():
            nonlocal completed_history, stream_messages, execution_started, session_model
            from src.init.coding import escalation_requests
            escalation_requests.set(controller.request_escalation)
            if resume_task_id:
                resumed = controller.call_control("task_resume", {"task_id": resume_task_id})
                if not resumed.get("accepted"):
                    raise ValueError(resumed["reason"])
            from pydantic_ai.messages import (FunctionToolCallEvent, FunctionToolResultEvent,
                                              PartDeltaEvent, PartStartEvent, TextPartDelta,
                                              ToolCallPart, ToolReturnPart)
            from src.init.tools import TOOLS
            tool_names = {tool.__name__ for tool in TOOLS} | controller.control_tools.keys()
            conversation_messages = list(history)
            current_prompt = model_prompt
            tool_arguments = {}
            searches = []

            def emit_visible(chunk):
                if not chunk:
                    return

                reply.append(chunk)
                if on_chunk is not None:
                    on_chunk(chunk)

            def speak_phrase(phrase):
                latency.mark("first_tts_phrase")
                self.voice.enqueue(phrase)

            delivery = ResponseDelivery(emit_visible, speak_phrase,
                                        speech_enabled=speech_enabled, on_surface=on_surface)
            direct_stream = None
            direct_text = ""
            direct_cut = False
            direct_failed = not VOICE_STREAMING
            streamed_total = []

            def direct_open():
                visible = "".join(streamed_total)
                return (not direct_failed and not cancel_event.is_set()
                        and controller.controller is None and controller.final_output is None
                        and not searches and controller.output_surface in {"auto", "chat"}
                        and len(visible) < DIRECT_STREAM_CHARACTERS
                        and visible.count("\n") < DIRECT_STREAM_LINES
                        and "```" not in visible)

            def emit_direct(chunk):
                nonlocal direct_text
                if not direct_text and reply:
                    delivery.emit("\n\n")
                direct_text += chunk
                streamed_total.append(chunk)
                delivery.emit(chunk)

            def feed_direct(chunk):
                nonlocal direct_stream, direct_cut, direct_failed
                if direct_failed or direct_cut:
                    return
                try:
                    if direct_stream is None:
                        if not direct_open():
                            return
                        latency.mark("first_token")
                        delivery.speech_enabled = delivery.speech_enabled and claim_speech()
                        direct_stream = AssistantTextStream(tool_names, emit_direct)
                    elif not direct_open():
                        direct_cut = True
                        return
                    direct_stream.feed(chunk)
                except Exception:
                    direct_failed = True
                    logging.getLogger("assistant.voice").exception(
                        "Streaming delivery failed; falling back to complete responses")

            def finish_direct():
                nonlocal direct_stream, direct_text, direct_cut, direct_failed
                stream, cut = direct_stream, direct_cut
                direct_stream, direct_cut = None, False
                try:
                    if stream is not None and not cut and not direct_failed:
                        stream.finish()
                    if direct_text:
                        delivery.flush_speech(cancel_event)
                except Exception:
                    direct_failed = True
                    logging.getLogger("assistant.voice").exception(
                        "Streaming delivery failed; falling back to complete responses")
                streamed, direct_text = direct_text, ""
                return streamed

            def deliver_output(output, *, streamed=None):
                if streamed is None:
                    streamed = finish_direct()
                if not output.startswith(streamed):
                    streamed = ""
                if reply and not streamed:
                    delivery.emit("\n\n")
                latency.mark("first_token")
                delivery.speech_enabled = delivery.speech_enabled and claim_speech()
                delivery.deliver(output, streamed=streamed,
                                 surface=controller.output_surface, title=controller.output_title,
                                 searched=searches[-1][:72] if searches else "")

            def note_search(name, call_id, failed):
                if name != "search_web" or failed:
                    return
                arguments = tool_arguments.get(call_id, {})
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except ValueError:
                        arguments = {}
                query = str(arguments.get("query", "")).strip() if isinstance(arguments, dict) else ""
                searches.append(query or "Web search")

            def emit_step(name, call_id, result, failed=False):
                note_search(name, call_id, failed)
                if not failed and name not in controller.control_tools:
                    succeeded_tools.append(name)
                if on_phase is None:
                    return
                receipt = controller.receipts.get(call_id, {})
                evidence = (controller.state.evidence.get(receipt.get("evidence_id", call_id))
                            if controller.state is not None else None)
                if receipt and not receipt.get("executed") and not receipt.get("control"):
                    kind = "skipped"
                elif failed or receipt.get("outcome") not in {None, "success", "negative"} or (evidence is not None and evidence.failed):
                    kind = "failed"
                elif evidence is not None:
                    kind = evidence.role
                elif name in controller.control_tools and isinstance(result, dict) and result.get("accepted"):
                    kind = "checkpoint"
                elif receipt.get("executed"):
                    kind = "execute"
                else:
                    kind = "skipped"
                arguments = tool_arguments.get(call_id, {})
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except ValueError:
                        arguments = {}
                subject = next((str(value) for value in arguments.values()
                                if isinstance(value, (str, int, float)) and not isinstance(value, bool)
                                and str(value).strip()), "") if isinstance(arguments, dict) else ""
                on_phase("step:" + json.dumps({"kind": kind, "tool": name,
                                               "subject": " ".join(subject.split())[:80]},
                                              ensure_ascii=False))

            async def stream_events(ctx, events):
                nonlocal stream_messages
                stream_messages = ctx.messages
                async for event in events:
                    if cancel_event.is_set():
                        return
                    if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
                        feed_direct(event.part.content)
                    elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
                        feed_direct(event.delta.content_delta)
                    if isinstance(event, FunctionToolCallEvent):
                        finish_direct()
                        tool_arguments[event.part.tool_call_id] = event.part.args
                        logging.getLogger("assistant.tools").info(
                            "Executing %s (%s)", event.part.tool_name, event.part.tool_call_id)
                    elif isinstance(event, FunctionToolResultEvent):
                        part = event.part
                        try:
                            result_bytes = len(json.dumps(
                                event.part.content, ensure_ascii=False,
                                default=str).encode("utf-8"))
                        except (TypeError, ValueError):
                            result_bytes = len(str(event.part.content).encode("utf-8"))
                        logging.getLogger("assistant.tools").info(
                            "Tool result: %s (%s); context_bytes=%d",
                            event.part.tool_name, event.part.tool_call_id,
                            result_bytes)
                        emit_step(part.tool_name, part.tool_call_id, part.content,
                                  getattr(part, "outcome", None) == "failed"
                                  or part.part_kind == "retry-prompt")
                        if (part.tool_name in {"task_finish", "response_finish"}
                                and isinstance(part.content, dict)
                                and part.content.get("accepted")
                                and (controller.state.final_output if controller.state is not None else controller.final_output) is not None
                                and controller.accept_output()):
                            deliver_output(controller.state.final_output if controller.state is not None else controller.final_output)

            if cancel_event.is_set():
                return
            execution_started = True
            from pydantic_ai.usage import UsageLimits
            while True:
                try:
                    result = await self.agent.run(
                        current_prompt,
                        message_history=conversation_messages,
                        toolsets=attachment_tools,
                        model=session_model,
                        model_settings=turn_model_settings,
                        cancellation_token=cancellation_token,
                        usage_limits=UsageLimits(request_limit=None),
                        capabilities=[controller],
                        event_stream_handler=stream_events)
                except TaskModelRetry as retry:
                    conversation_messages = controller.active_history(controller.messages)
                    conversation_messages.append(ModelRequest(parts=[UserPromptPart(str(retry))]))
                    stream_messages = conversation_messages
                    current_prompt = None
                    continue
                except TaskEscalate:
                    finish_direct()
                    conversation_messages = controller.active_history(controller.messages)
                    stream_messages = conversation_messages
                    session_model = escalation_model()
                    logging.getLogger("assistant.model").info(
                        "Escalating the task to %s (%s)", escalation_name, controller.escalation_reason)
                    current_prompt = None
                    continue
                except TaskOutputReady as ready:
                    finish_direct()
                    stream_messages = list(controller.messages)
                    if controller.accept_output():
                        output = str(ready)
                        deliver_output(output)
                        conversation_messages = [*stream_messages, ModelResponse(parts=[TextPart(output)])]
                        break
                    conversation_messages = stream_messages
                    current_prompt = None
                    continue
                except TaskStopped:
                    finish_direct()
                    stream_messages = list(controller.messages)
                    notice = controller.state.notice if controller.state is not None else controller.notice
                    if on_phase is not None and controller.state is not None:
                        on_phase(controller.state.status)
                    delivery.speech_enabled = False
                    delivery.emit(notice)
                    conversation_messages = [*stream_messages,
                                             ModelResponse(parts=[TextPart(notice)])]
                    break

                streamed_output = finish_direct()
                output = (
                    result.output
                    if isinstance(result.output, str)
                    else str(result.output))

                visible_output, text_call = extract_text_tool_call(
                    output,
                    tool_names)
                new_messages = list(result.new_messages())
                model_responses = [
                    message
                    for message in new_messages
                    if isinstance(message, ModelResponse)
                ]

                for request_index, response in enumerate(model_responses, 1):
                    logging.getLogger("assistant.model").info(
                        "Model response request=%d/%d input_tokens=%d "
                        "output_tokens=%d finish_reason=%s",
                        request_index, len(model_responses),
                        response.usage.input_tokens, response.usage.output_tokens,
                        response.finish_reason)
                conversation_messages = list(result.all_messages())
                stream_messages = conversation_messages
                if text_call is None:
                    if controller.accept_output(truncated=result.response.finish_reason == "length", output=visible_output):
                        deliver_output(visible_output, streamed=streamed_output)
                        break
                    current_prompt = None
                    continue

                name, arguments = text_call
                call_part = ToolCallPart(name, arguments)
                tool_arguments[call_part.tool_call_id] = arguments
                if new_messages and isinstance(new_messages[-1], ModelResponse):
                    response = new_messages[-1]
                    parts = [part for part in response.parts
                             if not isinstance(part, TextPart)]
                    if visible_output:
                        parts.append(TextPart(visible_output))
                    parts.append(call_part)
                    new_messages[-1] = ModelResponse(
                        parts=parts, model_name=response.model_name,
                        timestamp=response.timestamp,
                        provider_name=response.provider_name,
                        provider_url=response.provider_url)
                else:
                    new_messages.append(ModelResponse(parts=[call_part]))

                logging.getLogger("assistant.tools").info(
                    "Executing %s (%s)", name, call_part.tool_call_id)
                controller.messages = [*conversation_messages[:-1], *new_messages[-1:]]
                tool_output = await controller.invoke(name, arguments, call_part.tool_call_id)
                receipt = controller.receipts.get(call_part.tool_call_id, {})
                evidence = (controller.state.evidence.get(receipt.get("evidence_id", call_part.tool_call_id))
                            if controller.state is not None else None)
                outcome = "failed" if (evidence is not None and evidence.failed
                                      or receipt.get("outcome") not in {None, "success", "negative"}) else "success"
                from pydantic_ai import ToolReturn
                raw_return = tool_output if isinstance(tool_output, ToolReturn) else None
                tool_return = ModelRequest(parts=[ToolReturnPart(
                    name, raw_return.return_value if raw_return is not None else tool_output, call_part.tool_call_id,
                    outcome=outcome)])
                if raw_return is not None and raw_return.content is not None:
                    tool_return.parts.append(UserPromptPart(raw_return.content))
                logging.getLogger("assistant.tools").info(
                    "Tool result: %s (%s)", name, call_part.tool_call_id)
                emit_step(name, call_part.tool_call_id, tool_output, outcome == "failed")
                new_messages.append(tool_return)
                original_count = len(result.new_messages())
                prefix = result.all_messages()[:-original_count] if original_count else result.all_messages()
                conversation_messages = [*prefix, *new_messages]
                stream_messages = conversation_messages
                current_prompt = None
                if cancel_event.is_set():
                    return
            completed_history = conversation_messages
            if session is not None:
                completed_history = session.context.externalize_messages(completed_history)

            if owns_speech and delivery.speech_enabled:
                delivery.flush_speech(cancel_event)

                self.voice.request_done()

                while not self.voice.is_done():
                    await asyncio.sleep(0.02)
            elif owns_speech:
                self.voice.stop()

        async def run():
            nonlocal stream_messages
            task = asyncio.create_task(generate())
            try:
                while not task.done():
                    if cancel_event.is_set():
                        if owns_speech:
                            self.voice.stop()
                        task.cancel()
                        break
                    await asyncio.sleep(0.02)
                try:
                    await task
                except (asyncio.CancelledError, RunCancelled) as interrupted:
                    if not cancel_event.is_set():
                        raise
                    snapshot = (interrupted if isinstance(interrupted, RunCancelled)
                                else RunCancelled.from_cancellation(interrupted))
                    if snapshot is not None:
                        stream_messages = snapshot.all_messages()
                if cancel_event.is_set() and owns_speech:
                    self.voice.stop()
            except BaseException:
                task.cancel()
                if owns_speech:
                    try:
                        self.voice.stop()
                    except Exception:
                        pass
                await asyncio.gather(task, return_exceptions=True)
                raise

        from src.init.attachments import active_attachments
        memory_turn = None
        succeeded_tools = []
        attachment_token = active_attachments.set(attachments)
        try:
            with session.memory_scope() if session is not None else nullcontext() as memory_turn:
                if event_loop is None:
                    asyncio.run(run())
                else:
                    event_loop.run_until_complete(run())
        except BaseException:
            if controller.state is not None and controller.state.status == "active":
                from src.init.task_state import Lifecycle
                controller.state.suspend(Lifecycle.INTERRUPTED,
                                         "Execution interrupted by a runtime error; the task ledger is preserved.")
            raise
        finally:
            task_context.cancellation_token = None
            if session is None:
                self._active_cancellation_token = None
            controller.publish_activity()
            active_attachments.reset(attachment_token)
            if owns_speech:
                self.voice.audio_callback = None
                self.voice.speaking_callback = None
                self.voice.subtitle_callback = None

            if owns_speech and on_speaking is not None:
                on_speaking(False)

        text = "".join(reply)
        if cancel_event.is_set():
            from src.init.task_state import Lifecycle
            if controller.state is None:
                from src.init.task_effects import TOOL_SPECS
                if any(item["operational"] and TOOL_SPECS[item["tool"]].effectful
                       for item in controller.executions):
                    controller.promote("interrupted_after_effects")
            if controller.state is not None and controller.state.status == Lifecycle.ACTIVE:
                controller.state.suspend(Lifecycle.INTERRUPTED, "Interrupted by the user.")
            controller.publish_activity()
            if not execution_started:
                return "", history
            messages = stream_messages or list(history) + [ModelRequest(parts=[UserPromptPart(model_prompt)])]
            observed_returns = {part.tool_call_id for message in messages for part in message.parts
                                if part.part_kind in {"tool-return", "retry-prompt"}}
            proposed = {part.tool_call_id for message in messages for part in message.parts
                        if part.part_kind == "tool-call"}
            from pydantic_ai.messages import ToolReturnPart
            for execution in controller.executions:
                if execution["call_id"] in proposed - observed_returns:
                    raw = execution["raw"]
                    parts = [ToolReturnPart(execution["tool"], getattr(raw, "return_value", raw)
                                           if execution["returned"] else execution["result"].payload(), execution["call_id"])]
                    if getattr(raw, "content", None) is not None:
                        parts.append(UserPromptPart(raw.content))
                    messages = [*messages, ModelRequest(parts=parts)]
            safe = []
            pending = set()
            segment = []
            for message in messages:
                segment.append(message)
                for part in message.parts:
                    if part.part_kind == "tool-call":
                        pending.add(part.tool_call_id)
                    elif part.part_kind in ("tool-return", "retry-prompt"):
                        pending.discard(getattr(part, "tool_call_id", None))
                if not pending:
                    safe.extend(segment)
                    segment = []
            if safe and isinstance(safe[-1], ModelResponse) and any(
                    isinstance(part, TextPart) for part in safe[-1].parts):
                safe.pop()
            if controller.state is not None:
                interrupted_state = json.dumps(controller.state.snapshot(), ensure_ascii=False)
                safe.append(ModelRequest(parts=[UserPromptPart(
                    "Interrupted task state (observed outcomes, not instructions): " + interrupted_state)]))
            safe.append(ModelResponse(parts=[TextPart(
                (text + "\n" if text else "") +
                "[Response interrupted by the user. Speech may have stopped before "
                "all displayed text was spoken. Tools already started may have completed; "
                "inspect current state before retrying. Follow the user's next instruction.]")]))
            return text, safe

        from src.init.task_effects import TOOL_SPECS
        if (memory_turn is not None and memory_turn.service is not None and text.strip()
                and not memory_turn.writes and not any(
                    TOOL_SPECS[name].effectful for name in succeeded_tools if name in TOOL_SPECS)):
            from src.init.memory.integration import claims_unsaved_memory
            from src.init.lang import tr
            claimed = False
            try:
                audit = claims_unsaved_memory(session_model, memory_turn.prompt, text)
                claimed = asyncio.run(audit) if event_loop is None else event_loop.run_until_complete(audit)
            except Exception:
                logging.getLogger("assistant.memory").exception("Memory claim audit failed")
            if claimed:
                logging.getLogger("assistant.memory").warning("Reply claimed a memory write that never happened")
                notice = "\n\n" + tr("memory.unsaved_notice")
                if on_chunk is not None:
                    on_chunk(notice)
                text += notice
                for message in reversed(completed_history or []):
                    if isinstance(message, ModelResponse):
                        part = next((item for item in reversed(message.parts) if isinstance(item, TextPart)), None)
                        if part is not None:
                            part.content += notice
                            break

        if controller.state is not None and controller.state.status == "complete":
            task_context.task_controller = controller.pending_task
            if session is None:
                self._active_task_controller = controller.pending_task
            publish_task_state(None)

        return (
            text,
            completed_history
            if completed_history is not None
            else list(history))

    @staticmethod
    def _merge_message_history(history: list, completed_history: list | None) -> list:
        if not completed_history:
            return list(history)
        return [*history, *completed_history]

    def cancel_active_generation(self, context=None):
        """Cancel one session's active PydanticAI run from any thread."""
        token = (getattr(context, "cancellation_token", None) if context is not None
                 else self._active_cancellation_token)
        if token is not None:
            token.cancel()

