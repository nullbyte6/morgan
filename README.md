**NORA** is a Native Operational Reasoning Assistant, made for the 
local PC and meant to be running alongside your software. It is **100% open source and using Ollama local API**

## Installation

Use 64-bit Python 3.12 (also selected by `install.sh`). From the project folder:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

Windows media support uses the modular PyWinRT packages; do not install the
legacy `winrt` package. ShazamIO 0.8.1 or later is required for compatibility
with Pydantic AI.

## Voice Input
Run Nora and speak to it through `voice`. Speak after `[MIC]` shortly appears.
The LLM then stores said recording, decodes it, and executes the spoken 
command in the given language.

## Local files and Git

Use `cd D:\projects\my-app`, `cd ..`, or `cd /d "C:\My Projects"` directly
at the prompt, or ask Nora to change directory in natural language. `cd` alone
shows the current directory. Changes persist for the session: relative file and
Git operations use that directory. Initially the prompt is just `>>`; after a
successful `cd` (including `cd` alone), it shows the current path and active
Git branch (including from repository subdirectories), for example:

```text
>> D:\projects\my-app (main) >
```

The branch updates after switching branches; detached HEAD shows its short commit
ID. Outside Git repositories, only the path appears.

Nora can inspect, create, and edit local project files. It can also inspect Git
status and diffs, stage and commit changes, fetch or pull updates, push commits,
and work with repository history and branches. Tell Nora which repository to use
when it is not the current directory, and explicitly ask before you want changes
committed or published to a remote.
