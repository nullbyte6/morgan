```
 /$$   /$$                             
| $$$ | $$                             
| $$$$| $$  /$$$$$$   /$$$$$$  /$$$$$$ 
| $$ $$ $$ /$$__  $$ /$$__  $$|____  $$
| $$  $$$$| $$  \ $$| $$  \__/ /$$$$$$$
| $$\  $$$| $$  | $$| $$      /$$__  $$
| $$ \  $$|  $$$$$$/| $$     |  $$$$$$$
|__/  \__/ \______/ |__/      \_______/
```

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

## Configuration and personality

Nora uses `~/.nora/json/config.json`, independently of the current directory.
On first launch it creates this file with defaults, or imports a legacy repository
config if one exists. Existing user settings take precedence. Nora classifies
files directly inside `~/.nora` by extension: `.txt` into `note/`, `.md` into
`log/`, and `.json` into `json/`. Name collisions are left in place without
overwriting either file. Project files outside this folder are unaffected.

Edit the following settings in the user config while Nora is running:

```json
{
  "temperature": 0.3,
  "personality": {
    "tone": "short and direct",
    "verbosity": "brief",
    "humor": "subtle, when it fits",
    "formality": "informal",
    "instructions": "Use practical examples for complex concepts."
  }
}
```

These are fields to adjust in the full config; preserve the other settings.
Personality values are free text, in any language. Temperature accepts numbers
from 0 to 2. Changes apply automatically to the next response, without `reload`
or restarting; they do not modify a response already streaming. If an edit is
invalid, Nora warns and keeps the last valid configuration until the file is
corrected. Model name and keep-alive settings require restarting Nora;
`NORA_MODEL` and `NORA_KEEP_ALIVE` environment variables take precedence.

Notes are saved in `~/.nora/note/`; reading notes includes previous sessions.

## Session logs
Each launch saves a Markdown conversation in `~/.nora/.log/`, named
`YYYY-MM-DD_HH-MM-SS_microseconds.md` using the session's local start time.
It records the greeting, messages, voice transcripts, direct command results and
errors. Responses are saved as displayed, including partial responses if a stream
fails. At the next launch after 24 session logs, the oldest is removed to keep
24 logs including the new session. Other files are left alone.

## Weather

Ask "what will the weather be tomorrow morning in Madrid, Spain?" or choose a
default with "save Madrid, Spain as my weather location". After that, "what will
the weather be tomorrow morning?" uses the saved city. You can also edit
`weather_location` in `~/.nora/json/config.json`; an empty value means Nora asks
for a city when none is established in the conversation.

The Python tool calls [Open-Meteo](https://open-meteo.com/) over the Internet,
without an API key or extra dependencies. It supports up to 16 forecast days,
uses the destination's timezone and returns temperatures in °C. Morning means
06:00–12:00; period temperatures and daily minimum/maximum are reported separately.
This is a forecast service, not an offline weather model.

## Notifications and timers (Windows)

Ask Nora to "notify me to take a break in 10 minutes", "start a 5-minute tea
timer", "show my timers", or "cancel the tea timer". It can also send an
immediate notification. Each scheduled item has an ID, remaining time and status;
failed deliveries include an error. Multiple timers can run alongside conversation.

Timers run inside Nora: keep the process open until they finish. `reload` preserves
them, but exiting or restarting discards them. They do not wake a sleeping PC.
Windows notification settings determine whether the alert is displayed; a
successful submission does not confirm it was seen. Notifications use Windows
PowerShell and the built-in Windows Forms NotifyIcon, with no extra dependencies.

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
