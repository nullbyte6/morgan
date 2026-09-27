"""Audio-clock state machine for continuous wake + command capture.

Recognition runs outside this class: samples keep arriving during inference and
application startup. No Qt, microphone, or model is needed to test its timing.
"""
from __future__ import annotations

import math
import os
import re
from collections import deque
from dataclasses import dataclass

from .voice import pcm_rms
from .identity import get_assistant_name

SAMPLE_RATE = 16000
BLOCK_SECONDS = 0.1


def extract_command(text: str) -> str | None:
    """None means no wake prefix; an empty string means just the wake phrase."""
    name = re.escape(get_assistant_name())
    wake = re.compile(rf"^[\W_]*(?:(?:hola|hey|oye)[\W_]*{name}|{name})(?!\w)", re.I)
    match = wake.match(text)
    if match is None:
        return None
    command = re.sub(r"^[\W_]+", "", text[match.end():]).strip()
    return command[:1].upper() + command[1:]


@dataclass(frozen=True)
class WakeSettings:
    wait_seconds: float = 6.0
    silence_seconds: float = 1.2
    max_seconds: float = 120.0
    pre_roll_seconds: float = 0.3
    threshold: float = 400.0
    delivery_seconds: float = 300.0
    recognition_seconds: float = 60.0

    def __post_init__(self):
        for name, value in vars(self).items():
            if not math.isfinite(value) or value < 0 or (name != "pre_roll_seconds" and value == 0):
                raise ValueError(f"Invalid wake setting {name}: {value}")
        if self.max_seconds <= self.silence_seconds:
            raise ValueError("Wake maximum must exceed end silence")

    @classmethod
    def from_environment(cls):
        return cls(**{name: float(os.environ.get("ARLO_WAKE_" + name.upper(), default))
                      for name, default in vars(cls()).items()})


@dataclass(frozen=True)
class Snapshot:
    start: int
    end: int
    pcm: bytes
    final: bool = False


class WakeCapture:
    def __init__(self, settings: WakeSettings):
        self.settings = settings
        self.frames = deque()
        self.position = 0
        self.last_speech = 0
        self.idle_start = None
        self.active_start = None
        self.activated_at = 0
        self.wake_end = 0
        self.command_candidate = False
        self.last_request = 0
        self.retry_after = 0
        self.waiting = False
        self.event = None

    @staticmethod
    def blocks(seconds):
        return math.ceil(seconds / BLOCK_SECONDS)

    def feed(self, pcm: bytes):
        self.position += 1
        speech = pcm_rms(pcm) >= self.settings.threshold
        self.frames.append((self.position, pcm, speech))
        if speech:
            self.last_speech = self.position
            if self.idle_start is None:
                self.idle_start = max(1, self.position - self.blocks(self.settings.pre_roll_seconds))
            if self.active_start is not None and self.position > self.wake_end:
                self.command_candidate = True
        # Include inference latency without ever growing unbounded.
        keep = self.blocks(self.settings.max_seconds + self.settings.wait_seconds + 10)
        while len(self.frames) > keep:
            self.frames.popleft()

    def snapshot(self, start, *, final=False):
        return Snapshot(start, self.position,
                        b"".join(pcm for index, pcm, _ in self.frames if index >= start), final)

    def next_transcription(self) -> Snapshot | None:
        if self.waiting:
            return None
        silence = self.position - self.last_speech
        if self.active_start is not None:
            if self.position - self.active_start >= self.blocks(self.settings.max_seconds):
                # Never execute a command which may have been cut in half.
                self.event = "too_long"
                return None
            if self.command_candidate and self.last_speech > self.retry_after:
                if silence >= self.blocks(self.settings.silence_seconds):
                    self.waiting = True
                    return self.snapshot(self.active_start, final=True)
            elif self.position - self.activated_at >= self.blocks(self.settings.wait_seconds):
                self.event = "timeout"
            return None
        if self.idle_start is None or self.position - self.last_request < self.blocks(0.8):
            return None
        self.last_request = self.position
        self.waiting = True
        return self.snapshot(max(self.idle_start, self.position - self.blocks(8) + 1))

    def accept_transcript(self, snapshot: Snapshot, text: str) -> str | None:
        self.waiting = False
        command = extract_command(text)
        if snapshot.final:
            if command:
                return command
            # Wake-only partial detection can include its trailing syllable.
            # An empty final result must still allow the paused-command pattern.
            self.retry_after = snapshot.end
            self.command_candidate = self.last_speech > snapshot.end
            return None
        if command is not None:
            self.active_start = snapshot.start
            self.wake_end = snapshot.end
            self.activated_at = self.position
            # Always verify the complete utterance once. A short, low-beam
            # detection pass can recognize the name but omit the command that
            # was already spoken in the very same snapshot.
            self.command_candidate = True
            self.event = "activated"
        elif self.last_speech <= snapshot.end and self.position - self.last_speech >= self.blocks(self.settings.silence_seconds):
            self.idle_start = None
            self.frames.clear()
        return None
