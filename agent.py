import os
import re
import subprocess
import sys
import time

from colorama import just_fix_windows_console
from pydantic_ai import Agent, Tool
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, \
    UserPromptPart
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.providers.ollama import OllamaProvider

from src.init import brain
from src.init.brain import (
    MODEL_NAME, change_directory, get_working_directory,
    refresh_model_keep_alive, refresh)

from src.init.rules import INSTRUCTIONS
from src.init.output import plain_text_chunks
from src.init.spin import ASSISTANT_COLOR, RESET_COLOR, USER_COLOR, Spinner
from src.init.tools import TOOLS
from src.init.voice import VOICE_COMMANDS, capture_voice_input

os.environ["PYDANTIC_AI_NO_BANNER"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

just_fix_windows_console()
MODEL_SETTINGS = {
    "openai_reasoning_effort": "none",
    "temperature": 0.2,
}

model = OllamaModel(
    MODEL_NAME,
    provider=OllamaProvider(base_url="http://localhost:11434/v1"),
    settings=MODEL_SETTINGS,
)

TYPEWRITER_DELAY_SECONDS = float(
    os.environ.get("NORA_TYPEWRITER_DELAY", "0.002"))


def stream(chunks) -> None:
    """Print streamed text one character at a time."""
    sys.stdout.write(ASSISTANT_COLOR)
    try:
        for chunk in plain_text_chunks(chunks):
            for character in chunk:
                sys.stdout.write(character)
                sys.stdout.flush()
                if TYPEWRITER_DELAY_SECONDS:
                    time.sleep(TYPEWRITER_DELAY_SECONDS)
    finally:
        sys.stdout.write(f"{RESET_COLOR}\n")
        sys.stdout.flush()

def directory_cmd(command: str) -> str | None:
    """Handle standalone cd/chdir commands without a model or shell call."""
    match = re.fullmatch(r"(?:cd|chdir)(?=\s|\.|\\|$)\s*(.*)",
                         command.strip(), flags=re.IGNORECASE)
    if match is None:
        return None
    path = match.group(1)
    path = re.sub(r"^/d(?:\s+|$)", "", path, count=1, flags=re.IGNORECASE)
    return change_directory(path)


def git_cmd(command: str) -> str | None:
    """Execute exact supported Git commands through the existing tools."""
    commands = {
        "git push": brain.git_push,
        "git status": brain.git_status,
        "git diff": brain.git_diff,
        "git log": brain.git_log,
    }
    function = commands.get(command.strip())
    return function() if function is not None else None


def build_user_prompt() -> str:
    """Show the current location and live Git branch, including unborn branches."""
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


def read_user_input(prompt: str | None = None) -> str:
    """Read input with a normal prompt and the user's typed text in green."""
    if prompt is None:
        prompt = build_user_prompt()
    sys.stdout.write(f"{RESET_COLOR}{prompt}{USER_COLOR}")
    sys.stdout.flush()
    try:
        return input()
    finally:
        sys.stdout.write(RESET_COLOR)
        sys.stdout.flush()


agent = Agent(model=model,
    tools=[Tool(function, sequential=True) for function in TOOLS],
    instructions=INSTRUCTIONS)


@agent.instructions
def working_directory_instructions() -> str:
    return f"Current working directory for this turn: {get_working_directory()}"


def main():
    refresh_model_keep_alive()
    print("""
     /$$   /$$                             
    | $$$ | $$                             
    | $$$$| $$  /$$$$$$   /$$$$$$  /$$$$$$ 
    | $$ $$ $$ /$$__  $$ /$$__  $$|____  $$
    | $$  $$$$| $$  \\ $$| $$  \\__/ /$$$$$$$
    | $$\\  $$$| $$  | $$| $$      /$$__  $$
    | $$ \\  $$|  $$$$$$/| $$     |  $$$$$$$
    |__/  \\__/ \\______/ |__/      \\_______/
    """)
    print(brain.get_version())
    print("¡Hola! Me llamo Nora, ¿con qué te puedo ayudar?")
    history = []
    while True:
        user_input = read_user_input()
        if user_input.strip().lower() in ("quit", "exit"):
            break

        if user_input.strip().lower() in ("ref", "reload"):
            refresh()

        directory_result = directory_cmd(user_input)
        if directory_result is not None:
            print(directory_result)
            continue
        git_result = git_cmd(user_input)
        if git_result is not None:
            print(f"{ASSISTANT_COLOR}{git_result}{RESET_COLOR}")
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
                print(f"ERROR DE VOZ: {error}")
                continue
            if not user_input:
                continue
        spinner = Spinner()
        spinner.start()
        try:
            with agent.run_stream_sync(
                    user_input, message_history=history) as result:
                spinner.stop()
                stream(result.stream_text(delta=True, debounce_by=None))
                history = result.all_messages()
                refresh_model_keep_alive()
        except Exception as error:
            spinner.stop()
            print(f"ERROR: {error}")
            cause = error.__cause__
            if cause is not None:
                print(f"Detalle: {cause}")


if __name__ == "__main__":
    main()
