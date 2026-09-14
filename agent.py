import os
import shutil
import subprocess
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus, urlparse

from pydantic_ai import Agent
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.providers.ollama import OllamaProvider

os.environ["PYDANTIC_AI_NO_BANNER"] = "1"
model = OllamaModel(
    "qwen3:14b",
         provider=OllamaProvider(
        base_url="http://localhost:11434/v1"))

NOTES_FILE = Path(f"{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}.txt")
TYPEWRITER_DELAY_SECONDS = 0.01
APPLICATION_SUFFIXES = (".exe", ".com", ".bat", ".cmd", ".lnk", ".appref-ms")
_APPLICATION_SEARCH_CACHE: dict[str, list[dict[str, str]]] = {}


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
        frames = ("/", "--", "\\", "|")
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
    for chunk in chunks:
        for character in chunk:
            sys.stdout.write(character)
            sys.stdout.flush()
            if TYPEWRITER_DELAY_SECONDS:
                time.sleep(TYPEWRITER_DELAY_SECONDS)
    sys.stdout.write("\n")
    sys.stdout.flush()

def resolve_safe_path(path: str) -> Path:
    return Path(path).expanduser().resolve()


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


def read_file(path: str) -> str:
    try:
        file_path = resolve_safe_path(path)
        if not file_path.exists():
            return f"File does not exist: {file_path}"
        if not file_path.is_file():
            return f"Not a file: {file_path}"
        return file_path.read_text(encoding="utf-8")
    except Exception as error:
        return f"Error: {error}"


def write_file(path: str, content: str) -> str:
    try:
        file_path = resolve_safe_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return f"File written: {file_path}"
    except Exception as error:
        return f"Error: {error}"


def append_file(path: str, content: str) -> str:
    try:
        file_path = resolve_safe_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with file_path.open("a", encoding="utf-8") as file:
            file.write(content)
        return f"Content appended to: {file_path}"
    except Exception as error:
        return f"Error: {error}"


def replace_in_file(path: str, old_text: str, new_text: str) -> str:
    try:
        file_path = resolve_safe_path(path)
        if not file_path.exists():
            return f"File does not exist: {file_path}"
        content = file_path.read_text(encoding="utf-8")
        if old_text not in content:
            return "Text to replace was not found"
        occurrences = content.count(old_text)
        file_path.write_text(content.replace(old_text, new_text),
                             encoding="utf-8")
        return f"Replaced {occurrences} occurrence(s) in {file_path}"
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
            # DRIVE_FIXED = 3. This excludes optical, removable and network drives.
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
        if result.returncode != 0:
            return []
        data = json.loads(result.stdout)
        return data if isinstance(data, list) else [data]
    except Exception as error:
        return []


def list_applications() -> str:
    apps = get_applications()
    if not apps:
        return "No applications found"
    return "\n".join(sorted(app["Name"] for app in apps))


def open_application(application: str) -> str:
    query = application.strip().casefold()
    apps = get_applications()
    exact = [app for app in apps if app["Name"].casefold() == query]
    matches = exact or [app for app in apps if query in app["Name"].casefold()]
    if len(matches) == 1:
        app = matches[0]
        try:
            subprocess.Popen(
                ["explorer.exe", f"shell:AppsFolder\\{app['AppID']}"])
            return f"Opened application: {app['Name']}"
        except Exception as error:
            return f"Error: {error}"
    if len(matches) > 1:
        return ("Multiple applications found:"
                "\n") + "\n".join(app["Name"] for app in matches[:20])
    executable = shutil.which(application)
    if executable:
        try:
            subprocess.Popen([executable])
            return f"Opened application: {application}"
        except Exception as error:
            return f"Error: {error}"
    return f"Application not found: {application}"


agent = Agent(
    model=model,
    tools=[
        get_current_time,
        calculate,
        save_note,
        read_notes,
        list_files,
        read_file,
        write_file,
        append_file,
        replace_in_file,
        open_file,
        open_browser,
        search_web,
        list_applications,
        open_application
    ],
    instructions=(
        "You are a helpful personal desktop assistant developed by me, "
        "running 100% locally."
        "Use tools whenever useful. You may call multiple tools sequentially "
        "to complete a task."
        "Do not stop after the first tool if additional tools are required. "
        "Inspect files before modifying them when necessary. "
        "Prefer replace_in_file for precise edits instead of rewriting entire files. "
        "Use list_files when inspecting directories. "
        "When asked to open a file, application, website or search, actually "
        "use the corresponding tool."
        "When asked to open an application, use open_application directly. "
        "If you do not know the application's exact registered name, "
        "use list_applications first to find it. "
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
        "Keep answers short and friendly. Adapt your language to the user's "
        "language."
    )
)


def main():
    print("¡Hola! Me llamo Nora, ¿con qué te puedo ayudar?")
    history = []
    while True:
        user_input = input("> ")
        if user_input.strip().lower() in ("quit", "exit"):
            break
        try:
            result = agent.run_sync(user_input, message_history=history)
            history = result.all_messages()
            print(f"{result.output}")
        except Exception as error:
            print(f"ERROR: {error}")


if __name__ == "__main__":
    main()
