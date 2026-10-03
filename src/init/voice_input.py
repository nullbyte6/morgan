#  Copyright (c) 2026 Diego.
#
#  SPDX-License-Identifier: GPL-3.0-or-later
#
#  This file is part of arlo.
#
#  This program is free software: you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation, either version 3
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty
#  of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#  See the GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program. If not, see <https://www.gnu.org/licenses/>.
"""Microphone capture for spoken requests, independent of any interface toolkit."""
import logging
import threading

from src.init.attachments import DesktopVoiceMessage
from src.init.events import Event
from src.init.utils import spectrum_levels
from src.init.voice_ipc import desktop_audio


class VoiceInputRunner:
    """Body of a capture thread; a thread class supplies start and interruption."""
    levels = Event()
    processing = Event()
    speech_started = Event()
    utterance = Event()

    def __init__(self, *, automatic=False, live=False):
        self.automatic = automatic
        self.live = live
        self.capture = None
        self.partial = None
        self.waiting_response = threading.Event()
        self.stop_event = threading.Event()
        self.audio_wav = b""
        self.transcript = ""
        self.error = ""

    def interrupted(self):
        return False

    def run(self):
        try:
            from src.init.voice import record_voice, recording_to_wav

            with desktop_audio(stop_event=self.stop_event, tail=0):
                if self.interrupted():
                    return
                if self.live:
                    self.run_live()
                    return
                recording = record_voice(
                    on_audio=self.report_audio, stop_event=self.stop_event,
                    stop_on_silence=self.automatic)
                if self.interrupted():
                    return
            if recording is None:
                return
            self.processing.emit()
            self.audio_wav = recording_to_wav(*recording)
        except Exception as error:
            self.error = str(error)
            logging.getLogger("assistant.voice").exception("Voice input failed")

    def run_live(self):
        import sounddevice as sound
        from src.init import latency
        from src.init.voice import (LiveVoiceCapture, PartialTranscript,
                                    recording_to_wav)

        device = sound.query_devices(kind="input")
        sample_rate = int(device.get("default_samplerate") or 16000)
        self.capture = LiveVoiceCapture(sample_rate)
        with sound.RawInputStream(samplerate=sample_rate,
                                  blocksize=max(1, int(sample_rate * 0.05)),
                                  device=device["index"], channels=1,
                                  dtype="int16") as stream:
            while not self.stop_event.is_set() and not self.interrupted():
                data, overflow = stream.read(max(1, int(sample_rate * 0.05)))
                if overflow:
                    raise RuntimeError("Microphone overflow; restart voice conversation")
                pcm = bytes(data)
                if self.waiting_response.is_set():
                    self.capture.idle = 0.0
                recording = self.capture.feed(pcm)
                self.report_audio(pcm, sample_rate)
                if self.capture.event == "timeout":
                    return
                if self.capture.event == "started":
                    self.speech_started.emit()
                elif self.capture.event == "pause":
                    self.partial = PartialTranscript(
                        self.capture.snapshot(), sample_rate)
                elif self.capture.event == "resumed":
                    self.partial = None
                if recording is not None:
                    partial, self.partial = self.partial, None
                    latency.begin()
                    self.waiting_response.set()
                    self.processing.emit()
                    self.utterance.emit(DesktopVoiceMessage(
                        recording_to_wav(recording, sample_rate), live=True,
                        partial=partial))

    def playback(self, samples, sample_rate):
        capture = self.capture
        if capture is not None:
            capture.playback(samples, sample_rate)

    def report_audio(self, pcm_data, sample_rate):
        import numpy as np

        if (self.waiting_response.is_set() and self.capture is not None
                and not self.capture.started):
            return
        samples = np.frombuffer(pcm_data, dtype="<i2").astype(
            np.float32) / 32768.0
        self.levels.emit(spectrum_levels(samples, sample_rate).tolist())
