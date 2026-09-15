```

```

**NORA** is a Native Operational Reasoning Assistant runs locally alongside 
your software. It is **100% open source and uses the local Ollama API**.

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

## Assistant identity and runtime

Change `Assistant.name` in `agent.py` to rename the assistant. It is the single
source for greetings, model instructions, conversation logs, notifications,
installer messages (once Python is available), and the ASCII banner generated
by `pyfiglet`. Restart the process after editing the source.

`Assistant()` always returns the same instance, including imports made when
`agent.py` runs as a script. Reading `.name` does not initialize Ollama or the
terminal. `main()` calls `Assistant().run()`; the runtime is initialized once.

Tools obtain the shared instance through `src/init/identity.py`. `agent.py`
registers the singleton factory there; helper modules never import the entry
point. Runtime dependencies load only when needed, and configuration can load
independently of assistant registration.

Storage paths (`~/.nora`), `NORA_*` environment variables, the `nora.ps1`
launcher, existing tool identifiers, and the repository URL remain stable for
compatibility. They identify the project rather than its display name.

Run regression checks with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Configuration and personality
The assistant uses `~/.nora/json/config.json`, independently of the current directory.
On first launch it creates this file with defaults, or imports a legacy repository
config if one exists. Existing user settings take precedence. the assistant classifies
files directly inside `~/.nora` by extension: `.txt` into `note/`, `.md` into
`log/`, and `.json` into `json/`. Name collisions are left in place without
overwriting either file. Project files outside this folder are unaffected.

Edit the following settings in the user config while the assistant is running:

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
invalid, the assistant warns and keeps the last valid configuration until the file is
corrected. Model name and keep-alive settings require restarting the assistant;
`NORA_MODEL` and `NORA_KEEP_ALIVE` environment variables take precedence.

Notes are saved in `~/.nora/note/`; reading notes includes previous sessions.

## Session logs
Conversations are appended to `~/.nora/.log/YYYY-MM-DD.md` using the local date.
All launches on the same day share this file, with one header at its beginning.
Sessions running past midnight switch to the new day's file on the next message.
It records the greeting, messages, voice transcripts, direct command results and
errors. Responses are saved as displayed, including partial responses if a stream
fails. When opening a daily log, the oldest daily logs are removed to keep
24 daily files. Older logs named by session and other files are left alone.

### Private mode
Type `/private on` to pause Markdown logging and `/private off` to resume it.
`/private` toggles the mode; `/private status` shows its current state.
The alias `/private` also works. These commands run locally and are not logged.
While active, the prompt shows `[PRIVATE]` and no messages, voice transcripts,
command results, partial responses or errors are written to the conversation log.
Resuming only saves new messages; skipped messages are never appended later.
Private mode lasts until disabled or the assistant exits; a new launch starts with logging on.
This mode only pauses the Markdown log: conversation remains visible and in the
model's session context, so subsequent responses can still refer to it.

## Conversation scrolling (Windows)
Use ↑/↓ to scroll through the current conversation, including
while the assistant responds. Page Up/Page Down move by a page. The input stays visible;
typing returns to the latest output. Left/Right, Home/End and Delete edit your
message. Up/Down now scroll the conversation instead of recalling past commands.

## Playback and YouTube
Ask the assistant to pause, resume, go to the next track or return to the previous one.
`control_media` uses the active Windows media session, or an application's exact
source ID from `list_media_sessions`. Controls depend on what that application
supports; the assistant reports rejected or unsupported actions.

For a named song, the assistant searches YouTube with the local `yt-dlp` Python package.
Ambiguous requests produce a numbered list of titles and channels so you can
choose. The selected video opens in your default browser with autoplay requested.
Browser autoplay restrictions may require a click; opening the page alone does
not confirm playback. Next/previous on YouTube depends on the browser's exposed
media controls and available queue.

No paid APIs, API keys or downloads of audio/video are used. YouTube search and
playback need Internet. Install the updated `requirements.txt` and restart the assistant
to load the new tools. If YouTube changes its search interface, updating `yt-dlp`
may be necessary.

## Weather
Ask "what will the weather be tomorrow morning in Madrid, Spain?" or choose a
default with "save Madrid, Spain as my weather location". After that, "what will
the weather be tomorrow morning?" uses the saved city. You can also edit
`weather_location` in `~/.nora/json/config.json`; an empty value means the assistant asks
for a city when none is established in the conversation.

The Python tool calls [Open-Meteo](https://open-meteo.com/) over the Internet,
without an API key or extra dependencies. It supports up to 16 forecast days,
uses the destination's timezone and returns temperatures in °C. Morning means
06:00–12:00; period temperatures and daily minimum/maximum are reported separately.
This is a forecast service, not an offline weather model.

## Notifications and timers (Windows)
Ask the assistant to "notify me to take a break in 10 minutes", "start a 5-minute tea
timer", "show my timers", or "cancel the tea timer". It can also send an
immediate notification. Each scheduled item has an ID, remaining time and status;
failed deliveries include an error. Multiple timers can run alongside conversation.

Timers run inside the assistant: keep the process open until they finish. `reload` preserves
them, but exiting or restarting discards them. They do not wake a sleeping PC.
Windows notification settings determine whether the alert is displayed; a
successful submission does not confirm it was seen. Notifications use Windows
PowerShell and the built-in Windows Forms NotifyIcon, with no extra dependencies.

## Voice Input
Run the assistant and speak to it through `voice`. Speak after `[MIC]` shortly appears.
The LLM then stores said recording, decodes it, and executes the spoken 
command in the given language.

## Local files and Git
Use `cd D:\projects\my-app`, `cd ..`, or `cd /d "C:\My Projects"` directly
at the prompt, or ask the assistant to change directory in natural language. `cd` alone
shows the current directory. Changes persist for the session: relative file and
Git operations use that directory. Initially the prompt is just `>>`; after a
successful `cd` (including `cd` alone), it shows the current path and active
Git branch (including from repository subdirectories), for example:

```text
>> D:\projects\my-app (main) >
```

The branch updates after switching branches; detached HEAD shows its short commit
ID. Outside Git repositories, only the path appears.

The assistant can inspect, create, and edit local project files. It can also inspect Git
status and diffs, stage and commit changes, fetch or pull updates, push commits,
and work with repository history and branches. Tell the assistant which repository to use
when it is not the current directory, and explicitly ask before you want changes
committed or published to a remote.

## Messages (WhatsApp Cloud API)
Ask the assistant to send a message to a saved contact (for example, "manda a Mamá:
Llegaré a las ocho") or to an international number including its country code.
If the recipient or message is missing, the assistant asks and waits. Contact names match
exactly, ignoring case, accents and extra spaces; duplicate names require choosing
a number. Numbers are never inferred from the sender or a default contact.

The following fields in `~/.nora/json/config.json` are read on every send:

```json
{
  "message_service": "whatsapp",
  "whatsapp_phone_number_id": "",
  "whatsapp_api_version": ""
}
```

Fill `whatsapp_phone_number_id` with the sender ID from Meta's WhatsApp API setup,
and `whatsapp_api_version` with a supported Graph API version (`vNN.0`). Your
existing `phone_number` is preserved; a telephone number cannot replace Meta's ID.
Set `ACCESS_TOKEN` in the assistant's process environment before sending. Do not store the
token in the repository or conversation. WhatsApp is the currently implemented
service; other `message_service` values return an explicit unsupported error.

Contacts live in `~/.nora/json/contacts.json` and are read on each contact send:
```json
[
  {"name": "Example", "phone": "+34600000000"}
]
```

A direct number works without a contacts file. Texts support up to 4096 characters.
This integration uses the online WhatsApp Business Cloud API, not a personal
WhatsApp desktop session. Meta account setup and messaging restrictions apply.
See [Meta's Cloud API documentation](https://www.postman.com/meta/whatsapp-business-platform/documentation/wlk6lh4/whatsapp-cloud-api).
API acceptance is reported as submitted, not confirmed delivery. An uncertain
network result is not retried automatically to avoid duplicate messages.
Restart the assistant after installing this code to register the new tool; subsequent
configuration and contact edits do not require restarting. Test without sending
real messages with `python -m unittest discover -s tests -v`.
