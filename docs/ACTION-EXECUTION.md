# Desktop action execution

Typed messages and voice messages reach `AssistantWorker._ask`. Voice capture
converts microphone PCM to 16 kHz WAV and also obtains a local Whisper transcript
for the conversation log. The WAV is sent directly to the audio model
(`gemma4:e4b`, the same model as the default main model) as `input_audio`, with
the registered tools; the transcript is not used as an intermediate command.

Gemma also handles subsequent turns while the conversation contains audio.
Image attachments alone do not select the audio model. Gemma uses low reasoning
effort to select and chain tools; reasoning events are never displayed or spoken.
The provider combines Morgan's dynamic instructions into one system message.

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

If local transcription is unavailable, the voice log falls back to `[Voice input]`.
That marker is not a semantic memory query. Voice turns receive saved preferences
without automatically retrieving unrelated voice commands from previous sessions.

Restart the desktop application after updating this flow. Ordinary window close
hides the app; use the tray's quit action before launching it again. Future
hot reloads rebuild tools and clear the cached audio model.

## Verification

Run `.venv/Scripts/python.exe -B -m unittest discover -s test -v`.
The suite covers native audio on the actual HTTP adapter, streamed tool dispatch,
multiple actions, file writes and reads, a harmless real PowerShell command,
confirmation denial, cancellation, memory lookup, and reload. Power calls are
mocked so the tests never shut down Windows.

Live checks use the installed Ollama and Gemma with the full tool registry and
muted speech playback. File creation and command execution can be checked in a
temporary directory; power tool bodies must be substituted during these checks.
