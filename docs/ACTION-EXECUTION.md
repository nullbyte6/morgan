# Desktop action execution

Typed messages and voice messages reach `AssistantWorker._ask`. Voice capture
converts microphone PCM to 16 kHz WAV and transcribes it locally with Whisper.
The transcript is sent to the main model (`qwen3.5:4b` by default) as the user
message, with the registered tools. If the local transcription fails, the turn
ends with a transcription error; no audio model is used.

The main model uses low reasoning effort to select and chain tools; reasoning
events are never displayed or spoken. The provider combines Morgan's dynamic
instructions into one system message.

The agent consumes the complete model/tool loop. Native tool calls execute the
registered functions, tool results return to the model, and response text goes to
the desktop and TTS. `morgan.tools` logs each dispatched tool name and returned
result event without logging arguments. General shell commands retain their
existing confirmation callback; shell names such as `PowerShell` and `PWSH.EXE`
are normalized before validation.

Power requests follow this same model/tool path. `shutdown_computer()` means
immediate shutdown; a delayed request supplies seconds after the model converts
the requested duration. A scheduled notification only displays a message.
`kill_self` and `close_application("Morgan")` request a graceful Morgan exit after the
turn. Substring matching no
longer bypasses the model or defaults unrecognized durations to immediate power
off.

Restart the desktop application after updating this flow. Ordinary window close
hides the app; use the tray's quit action before launching it again. Future
hot reloads rebuild tools and the cached models.
