<p align="center">
  <img src="assets/arlo.png" alt="Arlo" width="200">
</p>

<h1 align="center">ARLO</h1>

Adaptive Reasoning Local Operator is a local desktop assistant that uses
Ollama to run tools and automate tasks on Windows.

## Installation

Run `ArloSetup.exe` (Windows 10 or later, 64-bit). No administrator rights are
required. The installer:

- installs `Arlo.exe` to `C:\Arlo` by default, with a Start menu entry and an
  optional desktop shortcut;
- asks for the assistant name (default `Arlo`) and sets the `ARLO` environment
  variable (or `<NAME>` for a custom name) to the installation folder;
- installs Git for Windows through WinGet if Git Bash is not found;
- installs Ollama through WinGet if it is missing, starts it, and downloads the
  `qwen3.5:9b` model (about 6.6 GB);
- creates the data directory `C:\Users\<username>\.arlo` and downloads the
  CosyVoice voice model (`Fun-CosyVoice3-0.5B-2512`, about 6.3 GB) from Hugging
  Face into `.arlo\models\Fun-CosyVoice3-0.5B` if it is missing. Interrupted
  downloads resume on the next run, and files already present are skipped;
- installs FFmpeg and Python 3.12 through WinGet if they are missing, and
  creates the voice runtime (`.venv` inside the installation folder) with
  PyTorch (CUDA build on NVIDIA GPUs, CPU build otherwise) and the CosyVoice
  dependencies. No repository clone is needed; when a cloned repository is
  found through `ARLO_HOME`, this step is skipped and its `.venv` is used.

Configuration and user data are stored in `C:\Users\<username>\.arlo`. Refer
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
`scripts\rebuild.bat` runs both steps. The installer is written to
`build\installer\ArloSetup.exe`. `dev\export_orb_icon.py` regenerates
`assets\arlo.ico` and `assets\arlo.png` from the orb widget.

## Usage

Closing the desktop window keeps Arlo and its local services running in the
background. On desktops with a system tray, use the Arlo icon to reopen it or
quit it completely. On other desktops, launch Arlo again to restore the existing
instance instead of starting another one.

After updating, restart both the desktop app and its persistent TTS service so
they use the same interruption protocol. Offline regression checks can be run
with `.venv/Scripts/python.exe -m unittest discover -s test -v`.

Hands-free voice activation uses a wake phrase to start Arlo's normal voice
recording, including in corner mascot mode. See
[wake voice setup and configuration](docs/WAKE-VOICE.md). After updating, 
restart
the desktop and the `ARLO_WAKE` task. Wake regression checks:
`.venv/Scripts/python.exe -B -m unittest discover -s tests -v`.

With the desktop open, `reload`, `ref`, or `/reload` hot-reloads Arlo's loaded
source/tool modules and rebuilds the model tool registry for the following turn.
Live process infrastructure (Qt bridges, locks, timers, sessions, and memory) is
preserved so reloading does not require restarting the application.

For native voice input, tool execution, and action regression checks, see
[desktop action execution](docs/ACTION-EXECUTION.md).