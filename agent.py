import os
import shutil
import subprocess
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus,urlparse

from pydantic_ai import Agent
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.providers.ollama import OllamaProvider

model=OllamaModel(
    "qwen3:14b",
    provider=OllamaProvider(
    base_url="http://localhost:11434/v1"))

NOTES_FILE=Path("notes.txt")
ALLOWED_ROOT=Path.home().resolve()

def resolve_safe_path(path:str)->Path:
    target=Path(path).expanduser()
    if not target.is_absolute():
        target=ALLOWED_ROOT/target
    target=target.resolve()
    try:
        target.relative_to(ALLOWED_ROOT)
    except ValueError:
        raise ValueError(f"Access denied: path must be inside {ALLOWED_ROOT}")
    return target

def get_current_time()->str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def calculate(expression:str)->str:
    if not set(expression)<=set("0123456789+-*/(). "):
        return "Error: only numbers and arithmetic operators are allowed"
    try:
        return str(eval(expression,{"__builtins__":{}},{}))
    except Exception as error:
        return f"Error: {error}"

def save_note(note:str)->str:
    with NOTES_FILE.open("a",encoding="utf-8") as file:
        file.write(f"- {note}\n")
    return "Note saved"

def read_notes()->str:
    if not NOTES_FILE.exists():
        return "No notes saved yet"
    return NOTES_FILE.read_text(encoding="utf-8")

def list_files(path:str=".")->str:
    try:
        folder=resolve_safe_path(path)
        if not folder.exists():
            return f"Directory does not exist: {folder}"
        if not folder.is_dir():
            return f"Not a directory: {folder}"
        items=[]
        for item in folder.iterdir():
            kind="DIR" if item.is_dir() else "FILE"
            items.append(f"[{kind}] {item.name}")
        return "\n".join(items) if items else "Directory is empty"
    except Exception as error:
        return f"Error: {error}"

def read_file(path:str)->str:
    try:
        file_path=resolve_safe_path(path)
        if not file_path.exists():
            return f"File does not exist: {file_path}"
        if not file_path.is_file():
            return f"Not a file: {file_path}"
        return file_path.read_text(encoding="utf-8")
    except Exception as error:
        return f"Error: {error}"

def write_file(path:str,content:str)->str:
    try:
        file_path=resolve_safe_path(path)
        file_path.parent.mkdir(parents=True,exist_ok=True)
        file_path.write_text(content,encoding="utf-8")
        return f"File written: {file_path}"
    except Exception as error:
        return f"Error: {error}"

def append_file(path:str,content:str)->str:
    try:
        file_path=resolve_safe_path(path)
        file_path.parent.mkdir(parents=True,exist_ok=True)
        with file_path.open("a",encoding="utf-8") as file:
            file.write(content)
        return f"Content appended to: {file_path}"
    except Exception as error:
        return f"Error: {error}"

def replace_in_file(path:str,old_text:str,new_text:str)->str:
    try:
        file_path=resolve_safe_path(path)
        if not file_path.exists():
            return f"File does not exist: {file_path}"
        content=file_path.read_text(encoding="utf-8")
        if old_text not in content:
            return "Text to replace was not found"
        occurrences=content.count(old_text)
        file_path.write_text(content.replace(old_text,new_text),
                             encoding="utf-8")
        return f"Replaced {occurrences} occurrence(s) in {file_path}"
    except Exception as error:
        return f"Error: {error}"

def open_file(path:str)->str:
    try:
        target=resolve_safe_path(path)
        if not target.exists():
            return f"Path does not exist: {target}"
        if os.name=="nt":
            os.startfile(target)
        elif os.name=="posix":
            opener="open" if shutil.which("open") else "xdg-open"
            subprocess.Popen([opener,str(target)])
        else:
            return "Unsupported operating system"
        return f"Opened: {target}"
    except Exception as error:
        return f"Error: {error}"

def open_browser(url:str)->str:
    try:
        if "://" not in url:
            url="https://"+url
        parsed=urlparse(url)
        if parsed.scheme not in ("http","https"):
            return "Error: only HTTP and HTTPS URLs are allowed"
        webbrowser.open(url)
        return f"Opened browser: {url}"
    except Exception as error:
        return f"Error: {error}"

def search_web(query:str)->str:
    url=f"https://www.google.com/search?q={quote_plus(query)}"
    webbrowser.open(url)
    return f"Opened web search for: {query}"

APPLICATIONS={
    "notepad":["notepad.exe"],
    "calculator":["calc.exe"],
    "explorer":["explorer.exe"],
    "terminal":["cmd.exe"],
    "powershell":["pwsh.exe"],
    "vscode":["code"]
}

def open_application(application:str)->str:
    application=application.strip().lower()
    command=APPLICATIONS.get(application)
    if command is None:
        return (f"Unknown application '{application}'. "
                f"Available applications: {', '.join(APPLICATIONS)}")
    try:
        subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        return f"Opened application: {application}"
    except FileNotFoundError:
        return f"Application '{application}' was configured but could not be found"
    except Exception as error:
        return f"Error: {error}"

agent=Agent(
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
        "Never claim an action succeeded unless the tool reported success. "
        "Keep answers short and friendly. Adapt your language to the user's "
        "language."
    )
)