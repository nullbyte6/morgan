# Hands-free wake commands

Run `scripts\setup.bat` to register the `ARLO_WAKE` logon task, or keep
`.venv\Scripts\python.exe -B -m entry.wake` running for interactive diagnostics.
The task runs `entry\wake.py` through the existing virtual environment. Restart
both the wake task and desktop after updating; an old desktop cannot consume the
new recording request or advertise its running state. No new dependencies or
service ports are required.

Say any of the following, wait for recording to begin, and then dictate the
request:

- “Arlo.”
- “Hola Arlo.”
- “Hey Arlo.”
- “Oye Arlo.”

Matching requires a complete wake phrase at the beginning of the recognized
utterance. Case, leading punctuation, punctuation between words, and the merged
recognition `HolaArlo` are accepted. `Carlos`, `hablarlo`, `Arlophone`, and mentions
of Arlo inside unrelated sentences do not activate it.

If the desktop is closed, the wake listener launches it and starts normal voice
recording as soon as it is ready. If it is already open, recording begins
automatically. This works while the window is visible, minimized, hidden, or in
mascot mode.
Recording stops after end silence, then the transcript is submitted so Arlo can
execute the request or answer conversationally. In mascot mode the mascot stays
in the corner: no full window is shown, restored, or focused, and the mascot
shrinks or grows with microphone intensity. Pending typed text and attachments
stay in the composer. The manual microphone button remains available and keeps
its click-to-start/click-to-stop behavior.

Successfully transcribed voice requests use the same model and tools as typed
requests. If transcription fails or is empty, the original recording is sent to
the configured audio model instead. A conversation containing native audio keeps
using the audio model so that its history can still be read.

## Capture and coordination

The listener maintains a continuous 16 kHz mono input stream, with 100 ms blocks.
RMS silence detection reuses the manual recorder's PCM utility. A single
background recognizer checks overlapping audio while the stream continues to
record. Once it recognizes the wake phrase, it closes its input stream, durably
queues a recording request, and launches the desktop when necessary. The desktop
then acquires the microphone through its normal voice-input path.

The wake listener reuses `transcribe_voice` with one multilingual Whisper model.
Short detection passes use the configured interface language (Spanish/English).
After activation, normal desktop recording performs command transcription and
retains its existing lazily loaded
`WHISPER_MODEL` (default `small`). As before, Whisper weights must be available
locally for fully offline use; first use of an uncached model may download them.

OS file locks in `%USERPROFILE%\.arlo\voice` coordinate microphone ownership.
Manual recording and the desktop agent request priority while processing. During
TTS playback, the desktop yields microphone ownership so the wake listener can
hear a new activation. A wake activation during speech stops the current response
and starts a fresh automatic recording as soon as the interrupted turn releases
audio. The listener drops partial captures and ignores outstanding recognition
results when yielding. Listening resumes after playback/cancellation and a 600 ms
speaker-tail guard. Locks release on process exit, including crashes; the UI never
waits synchronously for microphone handoff. A second wake listener also exits
immediately through an OS lock.

## Local delivery and recovery

`%USERPROFILE%\.arlo\voice\inbox.sqlite3` is the durable IPC inbox. There is no
network command endpoint or socket authentication to configure. It uses the
current Windows user's profile permissions; run both processes as the same user
and keep this directory private and on a local disk.

Each activation has a UUID. SQLite commits it before delivery, and the desktop
only claims pending recording requests after its worker reports readiness and is
idle. Busy/manual-recording states defer delivery. Transient database, microphone,
and recognition failures are logged and retried without replaying a claimed
request. Audio overflows discard the affected capture.
An unresponsive inference is abandoned after the recognition timeout; no second
model/inference is started until that worker returns. Restart the listener if a
native inference remains permanently stuck.

Queue states are `pending`, `dispatched`, `completed`, `failed`, and `expired`.
Dispatch uses **at-most-once** semantics: the claim is committed before starting
recording. If the desktop crashes after that claim, the request remains
`dispatched` and is not replayed automatically. Requests that have not been
claimed survive until their TTL expires (five minutes by default). Expired
requests never start a later recording.

Wake diagnostics are retained in `voice\wake.log` (rotated at 1 MB, two backups),
including queued IDs and capture errors. Transcriptions are not written to this
log. The inbox stores the internal recording-request marker and completion status
locally; normal desktop session logging applies after dictated text is submitted.

## Configuration

Set these environment variables for the user running the logon task, then restart
that task. For a foreground test, set `$env:ARLO_WAKE_WAIT_SECONDS = '8'` in
PowerShell before starting `wake.py`.

| Variable                        | Default | Meaning                                                                                             |
|---------------------------------|---------|-----------------------------------------------------------------------------------------------------|
| `ARLO_WAKE_WAIT_SECONDS`        | `6`     | Internal capture timeout after detection.                                                           |
| `ARLO_WAKE_SILENCE_SECONDS`     | `1.2`   | Silence threshold used by wake detection.                                                           |
| `ARLO_WAKE_MAX_SECONDS`         | `120`   | Safety limit for a listener capture.                                                                |
| `ARLO_WAKE_PRE_ROLL_SECONDS`    | `0.3`   | Audio retained before speech onset; `0` disables it.                                                |
| `ARLO_WAKE_THRESHOLD`           | `400`   | RMS speech threshold in signed 16-bit PCM units. Tune for microphone/noise level.                   |
| `ARLO_WAKE_DELIVERY_SECONDS`    | `300`   | Lifetime of an unclaimed recording request while the open app becomes ready.                        |
| `ARLO_WAKE_RECOGNITION_SECONDS` | `60`    | Maximum wait for an individual transcription.                                                       |
| `ARLO_WAKE_MODEL`               | `tiny`  | Listener's multilingual faster-whisper model; e.g. `small` for greater accuracy at higher CPU cost. |

Numeric values must be finite and positive except pre-roll, which may be zero.
Maximum duration must exceed end silence. Recognition quality and the RMS
threshold depend on the microphone and ambient noise; this is not a speaker
identification system.

## Verification

Run `.venv\Scripts\python.exe -B -m unittest discover -s tests -v`.
The regression tests cover wake matching, the recording-request round trip, and
exclusive desktop lifetime locking. They do not measure physical microphone,
Whisper, speaker echo, or Qt rendering behavior.

For a live acceptance check, restart the updated listener and close the desktop.
Say a wake phrase and confirm that Arlo opens and recording starts once it is
ready. Repeat with the full app already open and in mascot mode; in mascot mode,
verify that the full window stays hidden while the mascot changes size with your
voice. Also try the manual mic button and a response that speaks the name Arlo.
Check that there is one desktop instance, one agent request, no self-activation,
and that listening resumes after the reply.
