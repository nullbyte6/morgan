# Hands-free wake commands

Run the existing `setup.bat` to register the `ARLO_WAKE` logon task, or keep
`.venv\Scripts\python.exe -B wake.py` running for interactive diagnostics.
The task still runs `wake.py` through the existing virtual environment. Restart
both the wake task and desktop after updating; an old desktop cannot consume the
new inbox or cooperate with microphone ownership. No new dependencies or service
ports are required. The existing `arlo.bat` → `arlo-run.ps1` → services/desktop
launch path and desktop single-instance mutex remain in use.

Say any of the following:

- “Arlo, abre el navegador.”
- “Hola Arlo, abre Spotify.”
- “Hey Arlo.” Pause briefly, then “Qué hora es.”
- “Oye Arlo, …”

Matching requires a complete wake phrase at the beginning of the recognized
utterance. Case, leading punctuation, punctuation between words, and the merged
recognition `HolaArlo` are accepted. `Carlos`, `hablarlo`, `Arlophone`, and mentions
of Arlo inside unrelated sentences do not activate it. The wake phrase is removed
and the first command letter capitalized; the rest of the command is preserved.

**Mascot mode is supported.** Wake commands keep the mascot in the corner and use
its existing speaking/level indicators and normal TTS. They do not open the full
window. In full mode, a delivered command restores/focuses the existing window.
Pending typed text and attachments stay in the composer and are not included in
a wake request. The manual microphone button remains available.

## Capture and coordination

The listener maintains a continuous 16 kHz mono input stream, with 100 ms blocks.
RMS silence detection reuses the manual recorder's PCM utility. A single
background recognizer checks overlapping audio while the stream continues to
record. Detection starts the existing launcher immediately. The complete wake +
command audio remains buffered while recognition and desktop startup run.
Silence ends a command; the maximum duration is a safety ceiling, not a fixed
recording length. Reaching that ceiling discards the incomplete command instead
of executing a truncated instruction. A wake-only utterance returns to listening
after the speech-wait timeout without submitting an agent request.

The existing `transcribe_voice` function accepts an optional model, so wake
detection and final transcription reuse the listener's one multilingual Whisper
model. Only text crosses the process boundary; the desktop does not load another
STT model for a wake command. Short detection passes use the configured interface
language (Spanish/English); final transcription detects the command's language.
Manual recording retains its existing lazily loaded
`WHISPER_MODEL` (default `small`). As before, Whisper weights must be available
locally for fully offline use; first use of an uncached model may download them.

OS file locks in `%USERPROFILE%\.arlo\voice` coordinate microphone ownership.
Manual recording and the entire desktop agent/TTS turn request priority, wait for
the listener to close its stream, and then acquire ownership. The listener drops
partial captures and ignores outstanding recognition results when yielding. It
does not listen while Arlo is processing, confirming a tool, or speaking, so voice
barge-in during a response is intentionally unavailable. Text steering and the
existing stop button still work. Listening resumes after playback/cancellation
and a 600 ms speaker-tail guard. Locks release on process exit, including crashes;
the UI never waits synchronously for microphone handoff. A second wake listener
also exits immediately through an OS lock.

## Local delivery and recovery

`%USERPROFILE%\.arlo\voice\inbox.sqlite3` is the durable IPC inbox. There is no
network command endpoint or socket authentication to configure. It uses the
current Windows user's profile permissions; run both processes as the same user
and keep this directory private and on a local disk.

Each capture has a UUID. SQLite commits it before delivery, and the desktop only
claims pending commands after its existing worker reports readiness and is idle.
Busy/manual-recording states defer delivery. Startup attempts are throttled to
one every 30 seconds while unexpired pending commands exist. Transient database,
microphone, launcher, and recognition failures are logged and retried without
replaying a submitted command. Audio overflows discard the affected capture.
An unresponsive inference is abandoned after the recognition timeout; no second
model/inference is started until that worker returns. Restart the listener if a
native inference remains permanently stuck.

Queue states are `pending`, `dispatched`, `completed`, `failed`, and `expired`.
Dispatch uses **at-most-once** semantics: the claim is committed before calling
the existing agent pipeline. If the desktop crashes between that commit and
completion, the command remains `dispatched` and is not replayed automatically;
its tool effects may be unknown. This avoids duplicate external actions. Commands
that have not been claimed survive restarts and are delivered until their TTL
expires (five minutes by default). Expired requests never execute later. No
exactly-once guarantee is possible across arbitrary agent tool side effects.

Wake diagnostics are retained in `voice\wake.log` (rotated at 1 MB, two backups),
including queued IDs and capture errors. Transcriptions are not written to this
log. The inbox stores command text and completion status locally; normal desktop
session logging still applies when the agent executes a request.

## Configuration

Set these environment variables for the user running the logon task, then restart
that task. For a foreground test, set `$env:ARLO_WAKE_WAIT_SECONDS = '8'` in
PowerShell before starting `wake.py`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `ARLO_WAKE_WAIT_SECONDS` | `6` | Wait for command speech after wake detection. |
| `ARLO_WAKE_SILENCE_SECONDS` | `1.2` | Continuous silence that ends an utterance. Increase for slower speech. |
| `ARLO_WAKE_MAX_SECONDS` | `120` | Maximum buffered interaction duration, including wake audio and pauses. |
| `ARLO_WAKE_PRE_ROLL_SECONDS` | `0.3` | Audio retained before speech onset; `0` disables it. |
| `ARLO_WAKE_THRESHOLD` | `400` | RMS speech threshold in signed 16-bit PCM units. Tune for microphone/noise level. |
| `ARLO_WAKE_DELIVERY_SECONDS` | `300` | Lifetime of an unclaimed command during startup or busy periods. |
| `ARLO_WAKE_RECOGNITION_SECONDS` | `60` | Maximum wait for an individual transcription. |
| `ARLO_WAKE_MODEL` | `tiny` | Listener's multilingual faster-whisper model; e.g. `small` for greater accuracy at higher CPU cost. |

Numeric values must be finite and positive except pre-roll, which may be zero.
Maximum duration must exceed end silence. Recognition quality and the RMS
threshold depend on the microphone and ambient noise; this is not a speaker
identification system.

## Verification

Run `.venv\Scripts\python.exe -B -m unittest discover -s tests -v`.
Tests use synthetic PCM, temporary databases, actual OS locks (including a child
process), and offscreen Qt with the agent mocked. They cover command matching,
continuous audio through inference, pauses, long commands, timeouts, startup
delivery, retries, crash semantics, manual recording, and mascot/draft preservation.
They do not measure real Whisper accuracy or speaker echo on a physical device.

For a live acceptance check, restart the updated listener and desktop, then try
the example phrases with the app closed, fully visible, and in mascot mode. Try
a command longer than 30 seconds, a wake phrase with no command, the manual mic
button, and a response that speaks the name Arlo. Check that there is one desktop
instance, one agent request, no self-activation, and that listening resumes after
the reply. Normal desktop dependencies (including its current Steam discovery,
Ollama and TTS startup requirements) must work before this live check can pass.
