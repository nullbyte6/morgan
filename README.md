<p align="center">
  <img src="assets/arlo.png" alt="Arlo" width="200">
</p>

<h1 align="center">ARLO</h1>

Adaptive Reasoning Local Operator is a local desktop assistant that uses
Ollama to run tools and automate tasks on Windows.

## Features

- Local multimodal model (`gemma4:e4b` through Ollama) for text, images and
  voice, with tool calling to run commands, read and edit files and automate
  tasks on the PC.
- Spoken replies with CosyVoice, hands-free wake phrase activation and live
  voice input. See [wake voice](docs/WAKE-VOICE.md).
- Persistent local memory in SQLite, with pinned memories that are always in
  context. See [memory](docs/MEMORY.md).
- Nova, a personal organizer with reminders and events (flags and daily,
  weekly, monthly or custom repeats), a calendar, a diary of every day's
  conversations, a weekly review, memories and search. Arlo manages it from
  chat, and due reminders arrive as Windows notifications with snooze buttons.
- Tiling workspaces for editors, files, diffs, PDFs, terminals and Nova. See
  [workspaces](docs/WORKSPACES.md).
- File attachments and `@file` references. See
  [attachments](docs/ATTACHMENTS.md).
- Local PC health diagnostics tools. See [diagnostics](docs/DIAGNOSTICS.md).
- A health view in the command palette that checks Ollama, GPU use and the
  voice service.
- 26 built-in color themes and interface languages in Spanish, English and
  Chinese (Simplified).
- Settings buttons to back up and restore memories, Nova and the daily logs,
  and to check for updates from the GitHub releases.
- A lightweight terminal version that shares the desktop's runtime.

## Installation

Run `ArloSetup.exe` (Windows 10 or later, 64-bit). No administrator rights are
required. The installer:

- installs `Arlo.exe` to `C:\Arlo` by default, with a Start menu entry and an
  optional desktop shortcut, and the terminal version `ArloTUI.exe` with its
  own Start menu entry;
- asks for the assistant name (default `Arlo`) and sets the `ARLO` environment
  variable (or `<NAME>` for a custom name) to the installation folder;
- installs Git for Windows through WinGet if Git Bash is not found;
- installs Ollama through WinGet if it is missing, starts it, and downloads the
  `gemma4:e4b` model (about 6.6 GB), which handles both text and voice input;
- creates the data directory `C:\Users\<username>\.<name>` (`.arlo` for the
  default name), saves the chosen name in its `config.json`, and downloads the
  CosyVoice voice model (`Fun-CosyVoice3-0.5B-2512`, about 6.3 GB) from Hugging
  Face into `models\Fun-CosyVoice3-0.5B` inside it if it is missing. Interrupted
  downloads resume on the next run, and files already present are skipped;
- installs FFmpeg and Python 3.12 through WinGet if they are missing, and
  creates the voice runtime (`.venv` inside the installation folder) with
  PyTorch (CUDA build on NVIDIA GPUs, CPU build otherwise) and the CosyVoice
  dependencies. No repository clone is needed; when a cloned repository is
  found through `ARLO_HOME`, this step is skipped and its `.venv` is used.

Configuration and user data are stored in `C:\Users\<username>\.<name>`. Refer
to the source code and `config.json` to discover additional features and
configuration options.

To start Arlo, open it from the Start menu or run `Arlo.exe`. See the
[specs here](docs/SPECS.md) for model and hardware requirements.

## Running from source

Running from a clone requires Windows, PowerShell, Python 3.12 and Git, with
the dependencies from `requirements.txt` installed in a `.venv` virtual
environment at the repository root.

Start the desktop application with `scripts\arlo-start.bat`. It starts Ollama,
loads the model and the TTS service through `scripts\arlo-services.ps1`, and
then launches the installed `Arlo.exe` if one is found, or `entry.desktop` from
the `.venv` otherwise.

To build the executable, run `scripts/build-exe.sh` from Git Bash (PyInstaller,
output in `C:\Arlo` by default), then compile `ArloSetup.iss` with Inno Setup.
`scripts\rebuild.bat` builds the desktop and the terminal version
(`scripts/build-tui.sh`, output in `C:\Arlo\tui`, without Qt) and compiles the
installer, which requires both. `scripts\rebuild-tui.bat` rebuilds only the terminal
version before compiling; build the desktop first, because its build replaces the
whole `C:\Arlo` folder. The installer is written to
`build\installer\ArloSetup.exe`. `dev\export_orb_icon.py` regenerates
`assets\arlo.ico` and `assets\arlo.png` from the orb widget.

## Terminal version

`scripts\arlo-tui.bat` (or `.venv\Scripts\python.exe -m entry.tui`) starts a
lightweight dark terminal interface that shares the desktop's runtime, tools and
configuration, so it is always as up to date as the desktop. It has no orb,
workspaces or concurrent sessions: the assistant's name is drawn with pyfiglet,
followed by its version, and replies appear as subtitles synchronized with the
voice. The composer supports `@file` references, file attachments (button,
`Ctrl+O`, or pasting/dropping file paths), live voice input (button or `Ctrl+R`)
and direct shell commands when the text starts with `>`. `Ctrl+K` opens the action
palette, `F2` shows the last response, `Ctrl+J` inserts a new line, `Esc` or
`Ctrl+C` stops a response, and `Ctrl+D` exits. Nova opens from the palette,
with `Ctrl+Alt+N`, or on its diary with `Ctrl+L`, and offers the same agenda,
reminders, events, calendar, diary, week review, memories and search as the
desktop, with due reminders announced as Windows notifications. Pass `--no-voice` (or
`arlo-tui.bat -NoVoice`) to skip the TTS service entirely and show text only.

## Usage

Closing the desktop window keeps Arlo and its local services running in the
background. On desktops with a system tray, use the Arlo icon to reopen it or
quit it completely. On other desktops, launch Arlo again to restore the existing
instance instead of starting another one.

After updating, restart both the desktop app and its persistent TTS service so
they use the same interruption protocol. Arlo can also check for newer versions
from Settings or the command palette, download the installer and install it.

Hands-free voice activation uses a wake phrase to start Arlo's normal voice
recording, including in corner mascot mode. See
[wake voice setup and configuration](docs/WAKE-VOICE.md). After updating,
restart the desktop and the `ARLO_WAKE` task.

With the desktop open, `reload`, `ref`, or the Reload modules command in the
command palette hot-reloads Arlo's loaded source/tool modules and rebuilds the model tool registry for the following turn.
Live process infrastructure (Qt bridges, locks, timers, sessions, and memory) is
preserved so reloading does not require restarting the application.

For native voice input, tool execution, and action regression checks, see
[desktop action execution](docs/ACTION-EXECUTION.md).

## License

Arlo is free software released under the [GNU General Public License v3.0](LICENSE).
You can use, study, modify and share it, and anyone who distributes a modified
version must publish its source under the same license.

Arlo builds on third-party software that keeps its own licenses. Their license
texts are in the [licenses](licenses) directory and are installed with Arlo.
Models such as CosyVoice, Whisper and the Ollama models are covered by their own
terms, which may restrict some uses.
