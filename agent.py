import base64
import codecs
import ctypes
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.request
import wave
import webbrowser
from array import array
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus, urlparse

from colorama import Fore, Style, just_fix_windows_console
from pydantic_ai import Agent
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.providers.ollama import OllamaProvider

try:
    import winreg
except ImportError:
    winreg = None

os.environ["PYDANTIC_AI_NO_BANNER"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
just_fix_windows_console()
MODEL_NAME = os.environ.get("NORA_MODEL", "qwen3:14b")
MODEL_SETTINGS = {
    "openai_reasoning_effort": "none",
    "temperature": 0.2,
}
OLLAMA_KEEP_ALIVE = os.environ.get("NORA_KEEP_ALIVE", "30m")
USER_COLOR = Fore.GREEN
ASSISTANT_COLOR = Fore.CYAN
RESET_COLOR = Style.RESET_ALL
model = OllamaModel(
    MODEL_NAME,
    provider=OllamaProvider(base_url="http://localhost:11434/v1"),
    settings=MODEL_SETTINGS,
)

NOTES_FILE = Path(f"{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}.txt")
TYPEWRITER_DELAY_SECONDS = float(
    os.environ.get("NORA_TYPEWRITER_DELAY", "0.002"))
APPLICATION_SUFFIXES = (".exe", ".com", ".bat", ".cmd", ".lnk", ".appref-ms")
_APPLICATION_SEARCH_CACHE: dict[str, list[dict[str, str]]] = {}
VOICE_COMMANDS = {"/voice", "voice"}
VOICE_MODEL_NAME = os.environ.get("NORA_WHISPER_MODEL", "small")
VOICE_BLOCK_SECONDS = 0.1
VOICE_MAX_SECONDS = 30
VOICE_START_TIMEOUT_SECONDS = 10
VOICE_END_SILENCE_SECONDS = 1.2
VOICE_SILENCE_THRESHOLD = 400
_VOICE_MODEL = None


class Spinner:
    """Small terminal spinner shown while the agent is preparing its answer."""

    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._stop_event.clear()
        sys.stdout.write("\r/")
        sys.stdout.flush()
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()

    def _animate(self) -> None:
        frames = ("/", "-", "\\", "|")
        frame_index = 0
        while not self._stop_event.wait(0.1):
            sys.stdout.write(f"\r{frames[frame_index]}")
            sys.stdout.flush()
            frame_index = (frame_index + 1) % len(frames)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None
        sys.stdout.write("\r \r")
        sys.stdout.flush()


def print_stream_by_character(chunks) -> None:
    """Print streamed text one character at a time."""
    sys.stdout.write(ASSISTANT_COLOR)
    try:
        for chunk in chunks:
            for character in chunk:
                sys.stdout.write(character)
                sys.stdout.flush()
                if TYPEWRITER_DELAY_SECONDS:
                    time.sleep(TYPEWRITER_DELAY_SECONDS)
    finally:
        sys.stdout.write(f"{RESET_COLOR}\n")
        sys.stdout.flush()


def read_user_input(prompt: str = ">> ") -> str:
    """Read input with a normal prompt and the user's typed text in green."""
    sys.stdout.write(f"{RESET_COLOR}{prompt}{USER_COLOR}")
    sys.stdout.flush()
    try:
        return input()
    finally:
        sys.stdout.write(RESET_COLOR)
        sys.stdout.flush()


def keep_model_loaded() -> None:
    """Extend Ollama's model lifetime without delaying the next prompt."""
    payload = json.dumps({
        "model": MODEL_NAME,
        "prompt": "",
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "stream": False,
    }).encode("utf-8")
    request = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5):
            pass
    except (OSError, TimeoutError):
        pass


def refresh_model_keep_alive() -> None:
    """Refresh Ollama's keep-alive timer in the background."""
    threading.Thread(target=keep_model_loaded, daemon=True).start()


def pcm_rms(pcm_data: bytes) -> float:
    """Calculate the RMS volume of mono 16-bit PCM audio."""
    samples = array("h")
    samples.frombytes(pcm_data)
    if sys.byteorder == "big":
        samples.byteswap()
    if not samples:
        return 0.0
    return (sum(sample * sample for sample in samples) / len(samples)) ** 0.5


def record_voice() -> tuple[bytes, int] | None:
    """Record one utterance, starting and stopping automatically around speech."""
    try:
        import sounddevice as sound
    except ImportError as error:
        raise RuntimeError(
            "Voice input is not installed; run: pip install -r requirements.txt"
        ) from error

    device = sound.query_devices(kind="input")
    if int(device.get("max_input_channels", 0)) < 1:
        raise RuntimeError("No microphone input device is available")

    sample_rate = int(device.get("default_samplerate") or 16000)
    block_size = max(1, int(sample_rate * VOICE_BLOCK_SECONDS))
    maximum_blocks = int(VOICE_MAX_SECONDS / VOICE_BLOCK_SECONDS)
    start_timeout_blocks = int(
        VOICE_START_TIMEOUT_SECONDS / VOICE_BLOCK_SECONDS)
    silence_blocks_to_stop = int(
        VOICE_END_SILENCE_SECONDS / VOICE_BLOCK_SECONDS)

    audio_blocks: list[bytes] = []
    pre_roll: deque[bytes] = deque(maxlen=3)
    speech_started = False
    silent_blocks = 0

    with sound.RawInputStream(
            samplerate=sample_rate,
            blocksize=block_size,
            device=device["index"],
            channels=1,
            dtype="int16") as stream:
        for block_index in range(maximum_blocks):
            data, _ = stream.read(block_size)
            audio_block = bytes(data)
            contains_speech = pcm_rms(audio_block) >= VOICE_SILENCE_THRESHOLD

            if not speech_started:
                if contains_speech:
                    speech_started = True
                    audio_blocks.extend(pre_roll)
                    audio_blocks.append(audio_block)
                else:
                    pre_roll.append(audio_block)
                    if block_index >= start_timeout_blocks:
                        return None
                continue

            audio_blocks.append(audio_block)
            silent_blocks = 0 if contains_speech else silent_blocks + 1
            if silent_blocks >= silence_blocks_to_stop:
                break

    if not speech_started:
        return None
    return b"".join(audio_blocks), sample_rate


def get_voice_model():
    """Load the local multilingual speech model once, on first voice command."""
    global _VOICE_MODEL
    if _VOICE_MODEL is None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as error:
            raise RuntimeError(
                "Voice recognition is not installed; run: "
                "pip install -r requirements.txt"
            ) from error
        _VOICE_MODEL = WhisperModel(
            VOICE_MODEL_NAME, device="cpu", compute_type="int8")
    return _VOICE_MODEL


def transcribe_voice(pcm_data: bytes, sample_rate: int) -> tuple[str, str]:
    """Transcribe PCM audio locally and return its text and detected language."""
    audio_file = io.BytesIO()
    with wave.open(audio_file, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)
    audio_file.seek(0)

    segments, information = get_voice_model().transcribe(
        audio_file,
        language=None,
        task="transcribe",
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=False,
    )
    transcript = " ".join(
        segment.text.strip() for segment in segments if segment.text.strip()
    ).strip()
    return transcript, information.language


def capture_voice_input() -> str | None:
    """Capture and transcribe a single spoken command from the default microphone."""
    print("[MIC]", flush=True)
    recording = record_voice()
    if recording is None:
        print("No se detectó voz.")
        return None

    spinner = Spinner()
    spinner.start()
    try:
        transcript, language = transcribe_voice(*recording)
    finally:
        spinner.stop()
    if not transcript:
        print("No se pudo transcribir la voz.")
        return None
    print(f"{USER_COLOR}[VOICE:{language}] {transcript}{RESET_COLOR}")
    return json.dumps({
        "voice_language": language,
        "voice_text": transcript,
    }, ensure_ascii=False)


def resolve_safe_path(path: str) -> Path:
    return Path(path).expanduser().resolve()


def resolve_entry_path(path: str) -> Path:
    """Resolve a directory entry without following its final symbolic link."""
    return Path(os.path.abspath(Path(path).expanduser()))


def decode_text(data: bytes) -> tuple[str, str]:
    """Decode common Windows text formats and return text plus its encoding."""
    if data.startswith(codecs.BOM_UTF8):
        candidates = ("utf-8-sig",)
    elif data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        candidates = ("utf-16",)
    else:
        candidates = ("utf-8", "cp1252")

    for encoding in candidates:
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        control_characters = sum(
            ord(character) < 32 and character not in "\n\r\t\f\b"
            for character in text
        )
        if control_characters <= max(1, len(text) // 100):
            return text, encoding
    raise UnicodeError(
        "File is binary or uses an unsupported text encoding; use the binary tools"
    )


def atomic_write_bytes(path: Path, content: bytes) -> None:
    """Replace a file atomically so a failed write does not leave it truncated."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="wb", dir=path.parent, delete=False) as temporary_file:
            temporary_file.write(content)
            temporary_path = Path(temporary_file.name)
        os.replace(temporary_path, path)
    except Exception:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
        raise


def get_current_time() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def calculate(expression: str) -> str:
    if not set(expression) <= set("0123456789+-*/(). "):
        return "Error: only numbers and arithmetic operators are allowed"
    try:
        return str(eval(expression, {"__builtins__": {}}, {}))
    except Exception as error:
        return f"Error: {error}"


def save_note(note: str) -> str:
    with NOTES_FILE.open("a", encoding="utf-8") as file:
        file.write(f"- {note}\n")
    return "Note saved"


def read_notes() -> str:
    if not NOTES_FILE.exists():
        return "No notes saved yet"
    return NOTES_FILE.read_text(encoding="utf-8")


def list_files(path: str = ".") -> str:
    try:
        folder = resolve_safe_path(path)
        if not folder.exists():
            return f"Directory does not exist: {folder}"
        if not folder.is_dir():
            return f"Not a directory: {folder}"
        items = []
        for item in folder.iterdir():
            kind = "DIR" if item.is_dir() else "FILE"
            items.append(f"[{kind}] {item.name}")
        return "\n".join(items) if items else "Directory is empty"
    except Exception as error:
        return f"Error: {error}"


def create_directory(path: str, parents: bool = True) -> str:
    """Create a directory; optionally create all missing parent directories."""
    try:
        directory_path = resolve_safe_path(path)
        if directory_path.exists():
            if directory_path.is_dir():
                return f"Directory already exists: {directory_path}"
            return f"A file already exists at: {directory_path}"
        directory_path.mkdir(parents=parents, exist_ok=False)
        return f"Directory created: {directory_path}"
    except Exception as error:
        return f"Error: {error}"


def rename_directory(path: str, new_name: str) -> str:
    """Rename a directory in place; new_name must be a name, not another path."""
    try:
        directory_path = resolve_entry_path(path)
        if not directory_path.exists():
            return f"Directory does not exist: {directory_path}"
        if not directory_path.is_dir():
            return f"Not a directory: {directory_path}"
        if (not new_name.strip() or new_name in (".", "..")
                or Path(new_name).name != new_name):
            return f"Invalid directory name: {new_name}"
        destination = directory_path.with_name(new_name)
        if destination.exists() or destination.is_symlink():
            return f"Destination already exists: {destination}"
        directory_path.rename(destination)
        return f"Directory renamed: {directory_path} -> {destination}"
    except Exception as error:
        return f"Error: {error}"


def delete_directory(path: str, recursive: bool = False) -> str:
    """Delete a directory; recursive must be true to remove any contents."""
    try:
        directory_path = resolve_entry_path(path)
        if not directory_path.exists() and not directory_path.is_symlink():
            return f"Directory does not exist: {directory_path}"
        if not directory_path.is_dir():
            return f"Not a directory: {directory_path}"
        if directory_path == Path(directory_path.anchor):
            return f"Refusing to delete a filesystem root: {directory_path}"

        is_junction = (hasattr(directory_path, "is_junction")
                       and directory_path.is_junction())
        if directory_path.is_symlink():
            directory_path.unlink()
        elif is_junction:
            directory_path.rmdir()
        elif recursive:
            shutil.rmtree(directory_path)
        elif any(directory_path.iterdir()):
            return (f"Directory is not empty: {directory_path}. "
                    "Recursive deletion was not requested")
        else:
            directory_path.rmdir()
        return f"Directory deleted: {directory_path}"
    except Exception as error:
        return f"Error: {error}"


def read_file(path: str) -> str:
    """Read a text file while detecting UTF-8, UTF-16 or Windows-1252."""
    try:
        file_path = resolve_safe_path(path)
        if not file_path.exists():
            return f"File does not exist: {file_path}"
        if not file_path.is_file():
            return f"Not a file: {file_path}"
        content, _ = decode_text(file_path.read_bytes())
        return content
    except Exception as error:
        return f"Error: {error}"


def create_file(path: str, content: str = "", encoding: str = "utf-8") -> str:
    """Create a new text file and fail rather than overwrite an existing file."""
    try:
        file_path = resolve_safe_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with file_path.open("x", encoding=encoding) as file:
            file.write(content)
        return f"File created: {file_path}"
    except FileExistsError:
        return f"File already exists: {resolve_safe_path(path)}"
    except (LookupError, OSError) as error:
        return f"Error: {error}"


def write_file(path: str, content: str) -> str:
    """Create or completely overwrite a UTF-8 text file."""
    try:
        file_path = resolve_safe_path(path)
        atomic_write_bytes(file_path, content.encode("utf-8"))
        return f"File written: {file_path}"
    except Exception as error:
        return f"Error: {error}"


def edit_file(path: str, content: str) -> str:
    """Replace all text in an existing file while preserving its encoding."""
    try:
        file_path = resolve_safe_path(path)
        if not file_path.exists():
            return f"File does not exist: {file_path}"
        if not file_path.is_file():
            return f"Not a file: {file_path}"
        _, encoding = decode_text(file_path.read_bytes())
        atomic_write_bytes(file_path, content.encode(encoding))
        return f"File edited: {file_path}"
    except Exception as error:
        return f"Error: {error}"


def append_file(path: str, content: str) -> str:
    """Append text to a file, preserving its existing text encoding."""
    try:
        file_path = resolve_safe_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        encoding = "utf-8"
        if file_path.exists():
            if not file_path.is_file():
                return f"Not a file: {file_path}"
            _, encoding = decode_text(file_path.read_bytes())
        with file_path.open("a", encoding=encoding) as file:
            file.write(content)
        return f"Content appended to: {file_path}"
    except Exception as error:
        return f"Error: {error}"


def replace_in_file(path: str, old_text: str, new_text: str) -> str:
    """Replace matching text in an existing file without changing its encoding."""
    try:
        file_path = resolve_safe_path(path)
        if not file_path.exists():
            return f"File does not exist: {file_path}"
        if not file_path.is_file():
            return f"Not a file: {file_path}"
        content, encoding = decode_text(file_path.read_bytes())
        if old_text not in content:
            return "Text to replace was not found"
        occurrences = content.count(old_text)
        updated_content = content.replace(old_text, new_text)
        atomic_write_bytes(file_path, updated_content.encode(encoding))
        return f"Replaced {occurrences} occurrence(s) in {file_path}"
    except Exception as error:
        return f"Error: {error}"


def read_binary_file(path: str) -> str:
    """Read any binary file and return its bytes encoded as Base64."""
    try:
        file_path = resolve_safe_path(path)
        if not file_path.exists():
            return f"File does not exist: {file_path}"
        if not file_path.is_file():
            return f"Not a file: {file_path}"
        encoded = base64.b64encode(file_path.read_bytes()).decode("ascii")
        return encoded
    except Exception as error:
        return f"Error: {error}"


def write_binary_file(path: str, base64_content: str,
                      overwrite: bool = False) -> str:
    """Create a binary file from Base64; set overwrite only for an existing file."""
    try:
        file_path = resolve_safe_path(path)
        already_exists = file_path.exists()
        if already_exists and not overwrite:
            return f"File already exists: {file_path}"
        content = base64.b64decode(base64_content, validate=True)
        atomic_write_bytes(file_path, content)
        action = "edited" if already_exists else "created"
        return f"Binary file {action}: {file_path}"
    except (ValueError, OSError) as error:
        return f"Error: {error}"


def delete_file(path: str) -> str:
    """Permanently delete one file or symbolic link, never a directory."""
    try:
        file_path = resolve_entry_path(path)
        if not file_path.exists() and not file_path.is_symlink():
            return f"File does not exist: {file_path}"
        if file_path.is_dir() and not file_path.is_symlink():
            return f"Refusing to delete a directory: {file_path}"
        file_path.unlink()
        return f"File deleted: {file_path}"
    except Exception as error:
        return f"Error: {error}"


def open_file(path: str) -> str:
    try:
        target = resolve_safe_path(path)
        if not target.exists():
            return f"Path does not exist: {target}"
        if os.name == "nt":
            os.startfile(target)
        elif os.name == "posix":
            opener = "open" if shutil.which("open") else "xdg-open"
            subprocess.Popen([opener, str(target)])
        else:
            return "Unsupported operating system"
        return f"Opened: {target}"
    except Exception as error:
        return f"Error: {error}"


def open_browser(url: str) -> str:
    try:
        if "://" not in url:
            url = "https://" + url
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return "Error: only HTTP and HTTPS URLs are allowed"
        webbrowser.open(url)
        return f"Opened browser: {url}"
    except Exception as error:
        return f"Error: {error}"


def search_web(query: str) -> str:
    url = f"https://www.google.com/search?q={quote_plus(query)}"
    webbrowser.open(url)
    return f"Opened web search for: {query}"


def normalize_application_name(value: str) -> str:
    """Normalize an application name so matching is stable and accent-insensitive."""
    name = Path(value.strip()).stem
    name = unicodedata.normalize("NFKD", name.casefold())
    name = "".join(character for character in name
                   if not unicodedata.combining(character))
    return " ".join(re.findall(r"[a-z0-9]+", name))


def get_fixed_drive_roots() -> list[Path]:
    """Return every fixed local drive in deterministic order."""
    if os.name != "nt":
        return [Path("/")]

    roots = []
    drive_mask = ctypes.windll.kernel32.GetLogicalDrives()
    for index in range(26):
        if drive_mask & (1 << index):
            root = f"{chr(ord('A') + index)}:\\"
            if ctypes.windll.kernel32.GetDriveTypeW(root) == 3:
                roots.append(Path(root))
    return sorted(roots, key=lambda path: str(path).casefold())


def get_app_paths() -> list[dict[str, str]]:
    """Read executable paths registered by desktop applications."""
    if winreg is None:
        return []

    registry_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
    locations = (
        (winreg.HKEY_CURRENT_USER, winreg.KEY_READ),
        (winreg.HKEY_LOCAL_MACHINE,
         winreg.KEY_READ | winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE,
         winreg.KEY_READ | winreg.KEY_WOW64_32KEY),
    )
    apps = {}
    for hive, access in locations:
        try:
            with winreg.OpenKey(hive, registry_path, 0, access) as parent:
                subkey_count = winreg.QueryInfoKey(parent)[0]
                for index in range(subkey_count):
                    subkey_name = winreg.EnumKey(parent, index)
                    try:
                        with winreg.OpenKey(parent, subkey_name) as subkey:
                            executable = winreg.QueryValueEx(subkey, None)[0]
                    except OSError:
                        continue
                    executable = os.path.expandvars(str(executable)).strip('"')
                    if Path(executable).is_file():
                        key = executable.casefold()
                        apps[key] = {
                            "Name": Path(subkey_name).stem,
                            "Path": executable,
                        }
        except OSError:
            continue
    return sorted(apps.values(), key=lambda app: (
        normalize_application_name(app["Name"]), app["Path"].casefold()))


def get_applications() -> list[dict[str, str]]:
    """Read applications registered with Windows."""
    if os.name != "nt":
        return []
    start_apps = []
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", "Get-StartApps | "
                                                         "Select-Object Name,AppID | "
                                                         "ConvertTo-Json -Compress"],
            capture_output=True, text=True, encoding="utf-8")
        if result.returncode == 0:
            data = json.loads(result.stdout or "[]")
            start_apps = data if isinstance(data, list) else [data]
    except (OSError, json.JSONDecodeError):
        pass

    apps = [app for app in start_apps
            if app.get("Name") and app.get("AppID")]
    apps.extend(get_app_paths())
    return sorted(apps, key=lambda app: (
        normalize_application_name(app["Name"]),
        app.get("AppID", app.get("Path", "")).casefold()))


def find_applications_on_drive(root: Path, query: str) -> list[dict[str, str]]:
    """Find matching launchable files below one drive root."""
    matches = []
    for folder, folders, filenames in os.walk(
            root, onerror=lambda _: None, followlinks=False):
        folders[:] = [name for name in folders
                      if not Path(folder, name).is_junction()]
        for filename in filenames:
            path = Path(folder, filename)
            if not filename.casefold().endswith(APPLICATION_SUFFIXES):
                continue
            if query in normalize_application_name(filename):
                matches.append({
                    "Name": path.stem,
                    "Path": str(path),
                    "Source": "file",
                })
    return matches


def find_applications_on_all_drives(application: str) -> list[dict[str, str]]:
    """Find launchable files on every fixed disk, caching each normalized query."""
    query = normalize_application_name(application)
    if not query:
        return []
    if query in _APPLICATION_SEARCH_CACHE:
        return _APPLICATION_SEARCH_CACHE[query]

    roots = get_fixed_drive_roots()
    matches = []
    if roots:
        with ThreadPoolExecutor(max_workers=len(roots)) as executor:
            for drive_matches in executor.map(
                    lambda root: find_applications_on_drive(root, query), roots):
                matches.extend(drive_matches)

    matches.sort(key=lambda app: (normalize_application_name(app["Name"]),
                                  app["Path"].casefold()))
    _APPLICATION_SEARCH_CACHE[query] = matches
    return matches


def application_rank(app: dict[str, str], query: str) -> tuple:
    """Return a deterministic relevance order for an application candidate."""
    name = normalize_application_name(app["Name"])
    if name == query:
        match_rank = 0
    elif name.startswith(query):
        match_rank = 1
    elif all(word in name.split() for word in query.split()):
        match_rank = 2
    else:
        match_rank = 3

    helper_words = {"crash", "helper", "installer", "setup", "uninstall", "update"}
    helper_rank = int(bool(helper_words.intersection(name.split())))
    source_rank = 0 if app["Source"] == "registered" else 1
    target = app.get("AppID", app.get("Path", ""))
    return match_rank, helper_rank, source_rank, name, target.casefold()


def list_applications() -> str:
    apps = get_applications()
    if not apps:
        return "No applications found"
    return "\n".join(sorted(app["Name"] for app in apps))


def open_application(application: str) -> str:
    query = application.strip().casefold()
    normalized_query = normalize_application_name(query)
    if not normalized_query:
        return "Application name is empty"

    registered = [
        {**app, "Source": "registered" if app.get("AppID") else "file"}
        for app in get_applications()
        if normalized_query in normalize_application_name(app["Name"])
    ]
    matches = registered + find_applications_on_all_drives(application)
    if not matches:
        return f"Application not found: {application}"

    app = min(matches, key=lambda candidate:
              application_rank(candidate, normalized_query))
    try:
        if app["Source"] == "registered":
            subprocess.Popen(
                ["explorer.exe", f"shell:AppsFolder\\{app['AppID']}"])
        else:
            os.startfile(app["Path"])
        return f"Opened application: {app['Name']}"
    except Exception as error:
        return f"Error: {error}"


agent = Agent(
    model=model,
    tools=[
        get_current_time,
        calculate,
        save_note,
        read_notes,
        list_files,
        create_directory,
        rename_directory,
        delete_directory,
        read_file,
        create_file,
        edit_file,
        append_file,
        replace_in_file,
        read_binary_file,
        write_binary_file,
        delete_file,
        open_file,
        open_browser,
        search_web,
        list_applications,
        open_application
    ],
    instructions=(
        "You are a helpful personal desktop assistant developed by me, "
        "running 100% locally. "
        "On every turn, detect the language of the latest user message and answer "
        "entirely in that same language. The latest message takes precedence over "
        "the language used earlier in the conversation. Never switch to English "
        "just because a tool result or these instructions are in English. "
        "Microphone messages arrive as JSON with voice_language and voice_text. "
        "Treat voice_text as the exact user request, always answer in the language "
        "identified by voice_language, and never mention the JSON wrapper. "
        "Use tools whenever useful. You may call multiple tools sequentially "
        "to complete a task. "
        "Do not stop after the first tool if additional tools are required. "
        "Inspect files before modifying them when necessary. "
        "Use create_file for a new text file, edit_file to replace an existing "
        "text file, append_file to add text, and replace_in_file for precise edits. "
        "Use read_binary_file and write_binary_file for non-text formats. "
        "Only call delete_file when the latest user message explicitly asks to "
        "delete that specific file. Never infer permission to delete a file from "
        "a request to edit, replace, clean up, or recreate it. "
        "Use create_directory to make folders and rename_directory to rename them. "
        "Only call delete_directory when the latest user message explicitly asks "
        "to delete that specific folder. Set recursive to true only when the user "
        "explicitly asks to delete its contents as well, delete it recursively, or "
        "delete the whole folder. Never delete a broader parent folder. "
        "Use list_files when inspecting directories. "
        "When asked to open a file, application, website or search, actually "
        "use the corresponding tool. "
        "When asked to open an application, use open_application directly. "
        "When the user says to open X without mentioning a website, URL, "
        "browser or web page, always try open_application first. "
        "Do not open a website for an application name unless the user explicitly "
        "asks for the website, web version, browser or URL. "
        "If open_application reports that the application was not found, tell the user "
        "instead of automatically opening its website. "
        "Use open_browser only when the user explicitly refers to a website, "
        "URL, domain, browser or web page. "
        "Use search_web only when the user explicitly asks to search the web. "
        "Never claim an action succeeded unless the tool reported success. "
        "Keep answers short and friendly."
    )
)


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
    print("¡Hola! Me llamo Nora, ¿con qué te puedo ayudar?")
    history = []
    while True:
        user_input = read_user_input()
        if user_input.strip().lower() in ("quit", "exit"):
            break
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
                print_stream_by_character(
                    result.stream_text(delta=True, debounce_by=None))
                history = result.all_messages()
                refresh_model_keep_alive()
        except Exception as error:
            spinner.stop()
            print(f"ERROR: {error}")


if __name__ == "__main__":
    main()
