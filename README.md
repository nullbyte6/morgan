# ARLO
Adaptive Reasoning Local Operator is a local desktop assistant that uses 
Ollama to run tools and automate tasks on Windows. It requires Windows, PowerShell, Python 3.12, and Ollama. The `arlo.ps1` launcher starts the application using the `.venv` virtual environment.
Configuration and user data are stored in `C:\Users\<username>\.arlo`. Refer to the source code and `config.json` to discover additional features and configuration options.
You can install Arlo from Git Bash or WSL by running the repository installer 
directly:

```bash
curl -fsSL https://raw.githubusercontent.com/xddigs/arlo/main/install.sh | bash
```

The installation script creates the virtual environment, installs the required dependencies, sets up Ollama, and downloads the configured model.
If you have already cloned the repository, navigate to its directory and run:

```bash
bash install.sh
```
For an existing installation, you can start arlo directly by running `arlo.ps1`.

The desktop interface (`arloui.bat`) has a language switch directly below the
subtitles switch. Off selects English and on selects Spanish. Changes apply
immediately and are saved as `"lang": "english"` or `"lang": "spanish"` in
`~/.arlo/json/config.json`. Shared interface text is resolved by `src/init/lang.py`
from `src/init/locales/lang_en.json` and `lang_es.json`. Keep both catalogs' keys
and formatting placeholders in sync when adding interface text. The assistant
continues to answer in the language of the user's message.

While Arlo is speaking, Send becomes Stop. Clicking it interrupts the response
and discards pending speech, keeping any text you are composing. To steer a
response, type a correction and press Enter: the current turn is interrupted,
then the correction runs with the conversation history. Shift+Enter inserts a
newline. The input also accepts steering while Arlo is thinking. Stopping a
response does not undo actions a tool has already performed.

After updating, restart both the desktop app and its persistent TTS service so
they use the same interruption protocol. Offline regression checks can be run
with `.venv/Scripts/python.exe -m unittest discover -s tests -v`.
