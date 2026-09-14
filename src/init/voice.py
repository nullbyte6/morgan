import io
import json
import os
import sys
import wave
from array import array
from collections import deque

from .spin import RESET_COLOR, USER_COLOR, Spinner

VOICE_COMMANDS = {"/voice", "voice"}
VOICE_MODEL_NAME = os.environ.get("NORA_WHISPER_MODEL", "small")
VOICE_BLOCK_SECONDS = 0.1
VOICE_MAX_SECONDS = 30
VOICE_START_TIMEOUT_SECONDS = 10
VOICE_END_SILENCE_SECONDS = 1.2
VOICE_SILENCE_THRESHOLD = 400
_VOICE_MODEL = None


def pcm_rms(pcm_data: bytes) -> float:
    """Calculate the RMS volume of mono 16-bit PCM audio."""
    samples = array("h")
    samples.frombytes(pcm_data)
    if sys.byteorder == "big":
        samples.byteswap()
    if not samples:
        return 0.0
    return (sum(sample * sample for sample in samples) / len(samples)) ** 0.5


def record_voice() -> tuple[bytes, int] | None:
    """Record one utterance, starting and stopping automatically around speech."""
    try:
        import sounddevice as sound
    except ImportError as error:
        raise RuntimeError(
            "Voice input is not installed; run: pip install -r requirements.txt"
        ) from error

    device = sound.query_devices(kind="input")
    if int(device.get("max_input_channels", 0)) < 1:
        raise RuntimeError("No microphone input device is available")

    sample_rate = int(device.get("default_samplerate") or 16000)
    block_size = max(1, int(sample_rate * VOICE_BLOCK_SECONDS))
    maximum_blocks = int(VOICE_MAX_SECONDS / VOICE_BLOCK_SECONDS)
    start_timeout_blocks = int(
        VOICE_START_TIMEOUT_SECONDS / VOICE_BLOCK_SECONDS)
    silence_blocks_to_stop = int(
        VOICE_END_SILENCE_SECONDS / VOICE_BLOCK_SECONDS)

    audio_blocks: list[bytes] = []
    pre_roll: deque[bytes] = deque(maxlen=3)
    speech_started = False
    silent_blocks = 0

    with sound.RawInputStream(
            samplerate=sample_rate,
            blocksize=block_size,
            device=device["index"],
            channels=1,
            dtype="int16") as stream:
        for block_index in range(maximum_blocks):
            data, _ = stream.read(block_size)
            audio_block = bytes(data)
            contains_speech = pcm_rms(audio_block) >= VOICE_SILENCE_THRESHOLD

            if not speech_started:
                if contains_speech:
                    speech_started = True
                    audio_blocks.extend(pre_roll)
                    audio_blocks.append(audio_block)
                else:
                    pre_roll.append(audio_block)
                    if block_index >= start_timeout_blocks:
                        return None
                continue

            audio_blocks.append(audio_block)
            silent_blocks = 0 if contains_speech else silent_blocks + 1
            if silent_blocks >= silence_blocks_to_stop:
                break

    if not speech_started:
        return None
    return b"".join(audio_blocks), sample_rate


def get_voice_model():
    """Load the local multilingual speech model once, on first voice command."""
    global _VOICE_MODEL
    if _VOICE_MODEL is None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as error:
            raise RuntimeError(
                "Voice recognition is not installed; run: "
                "pip install -r requirements.txt"
            ) from error
        _VOICE_MODEL = WhisperModel(
            VOICE_MODEL_NAME, device="cpu", compute_type="int8")
    return _VOICE_MODEL


def transcribe_voice(pcm_data: bytes, sample_rate: int) -> tuple[str, str]:
    """Transcribe PCM audio locally and return its text and detected language."""
    audio_file = io.BytesIO()
    with wave.open(audio_file, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)
    audio_file.seek(0)

    segments, information = get_voice_model().transcribe(
        audio_file,
        language=None,
        task="transcribe",
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=False,
    )
    transcript = " ".join(
        segment.text.strip() for segment in segments if segment.text.strip()
    ).strip()
    return transcript, information.language


def capture_voice_input() -> str | None:
    """Capture and transcribe a single spoken command from the default microphone."""
    print("[MIC]", flush=True)
    recording = record_voice()
    if recording is None:
        print("No se detectó voz.")
        return None

    spinner = Spinner()
    spinner.start()
    try:
        transcript, language = transcribe_voice(*recording)
    finally:
        spinner.stop()
    if not transcript:
        print("No se pudo transcribir la voz.")
        return None
    print(f"{USER_COLOR}[VOICE:{language}] {transcript}{RESET_COLOR}")
    return json.dumps({
        "voice_language": language,
        "voice_text": transcript,
    }, ensure_ascii=False)
