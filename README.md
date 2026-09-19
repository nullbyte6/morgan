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

Arlo also has a desktop interface application (`arloui.bat`) which, if you 
ask me, works better for the public and for my own development.

See more of its usage/application when you launch the script :) 

After updating, restart both the desktop app and its persistent TTS service so
they use the same interruption protocol. Offline regression checks can be run
with `.venv/Scripts/python.exe -m unittest discover -s test -v`.
