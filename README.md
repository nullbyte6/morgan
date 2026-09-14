**NORA** is a Native Operational Reasoning Assistant, made for the 
local PC and meant to be running alongside your software. It is **100% open source and using Ollama local API**

## Installation

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Voice Input
Run Nora and speak to it through `voice`. Speak after `[MIC]` shortly appears.
The LLM then stores said recording, decodes it, and executes the spoken 
command in the given language.

## Local files and Git

Nora can inspect, create, and edit local project files. It can also inspect Git
status and diffs, stage and commit changes, fetch or pull updates, push commits,
and work with repository history and branches. Tell Nora which repository to use
when it is not the current directory, and explicitly ask before you want changes
committed or published to a remote.
