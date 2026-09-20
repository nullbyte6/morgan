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

from __future__ import annotations

import ctypes
import logging
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

from src.init.lang import tr

ROOT = Path(__file__).resolve().parent
LAUNCHER = ROOT / "arlo.bat"

SAMPLE_RATE = 16000
CHUNK_SECONDS = 2.0
COOLDOWN_SECONDS = 10
TRIGGERS = ("holaarlo", "hola arlo", "arlo", "ARLO")

logging.basicConfig(
    level=logging.INFO,
    format="[Wake] %(message)s")

log = logging.getLogger("arlo.wake")

def normalize(text: str) -> str:
    import unicodedata

    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        char for char in text
        if not unicodedata.combining(char)
    )

    return " ".join(
        "".join(
            char if char.isalnum() else " "
            for char in text.lower()
        ).split()
    )


def is_arlo_running() -> bool:
    """Check whether an Arlo desktop instance is running."""
    if sys.platform != "win32":
        return False

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenMutexW.argtypes = [
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_wchar_p,
    ]
    kernel32.OpenMutexW.restype = ctypes.c_void_p

    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int

    SYNCHRONIZE = 0x00100000
    ERROR_ACCESS_DENIED = 5

    handle = kernel32.OpenMutexW(
        SYNCHRONIZE,
        False, r"Local\Diego.Arlo.Desktop",)

    if handle:
        kernel32.CloseHandle(handle)
        return True

    error = ctypes.get_last_error()
    if error == ERROR_ACCESS_DENIED:
        return True

    return False

def launch_arlo() -> None:
    if not LAUNCHER.is_file():
        log.error(tr("wake.launcher_not_found", path=LAUNCHER))
        return

    if is_arlo_running():
        log.info(tr("wake.already_running"))
        return

    log.info(tr("wake.activation_detected"))
    subprocess.Popen(
        ["cmd.exe", "/c", str(LAUNCHER)],
        cwd=str(ROOT),
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )


def main() -> None:
    log.info(tr("wake.loading_model"))

    model = WhisperModel(
        "tiny",
        device="cpu",
        compute_type="int8",
    )

    log.info(tr("wake.listening", phrase="Hola Arlo"))
    last_activation = 0.0

    while True:
        audio = sd.rec(
            int(SAMPLE_RATE * CHUNK_SECONDS),
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32")

        sd.wait()
        samples = np.asarray(
            audio[:, 0],
            dtype=np.float32)

        rms = float(np.sqrt(np.mean(samples ** 2)))
        if rms < 0.008:
            continue

        segments, _ = model.transcribe(
            samples,
            language="es",
            beam_size=1,
            condition_on_previous_text=False)

        text = normalize(
            " ".join(segment.text for segment in segments))

        if not text:
            continue

        log.info(tr("wake.recognized", text=text))
        if not any(trigger in text for trigger in TRIGGERS):
            continue

        now = time.monotonic()
        if now - last_activation < COOLDOWN_SECONDS:
            continue

        last_activation = now
        launch_arlo()


if __name__ == "__main__":
    # noinspection PyBroadException
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception:
        log.exception(tr("wake.detector_error"))
        sys.exit(1)
