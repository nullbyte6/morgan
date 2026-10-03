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
"""Discover voice references independently of the model and desktop runtime."""

import re
import sys
from pathlib import Path

VOICE_DIR = Path(__file__).resolve().parents[1] / "voices"
OMNI_MODEL_NAME = "MiniCPM-o-4_5-gguf"
OMNI_MODEL_FILE = "MiniCPM-o-4_5-Q4_K_M.gguf"
OMNI_MODEL_FILES = (
    OMNI_MODEL_FILE,
    "audio/MiniCPM-o-4_5-audio-F16.gguf",
    "tts/MiniCPM-o-4_5-tts-F16.gguf",
    "tts/MiniCPM-o-4_5-projector-F16.gguf",
    "vision/MiniCPM-o-4_5-vision-F16.gguf",
    "token2wav-gguf/encoder.gguf",
    "token2wav-gguf/flow_extra.gguf",
    "token2wav-gguf/flow_matching.gguf",
    "token2wav-gguf/hifigan2.gguf",
    "token2wav-gguf/prompt_cache.gguf",
)


def omni_model() -> Path:
    from .config import HOME_PATH

    return HOME_PATH / "models" / OMNI_MODEL_NAME / OMNI_MODEL_FILE


def omni_server_executable() -> Path:
    from .config import HOME_PATH, load_config

    configured = load_config().get("omni_server", "")
    if configured:
        return Path(configured)
    name = "llama-omni-server.exe" if sys.platform == "win32" else "llama-omni-server"
    build = "build-hip2" if sys.platform == "win32" else "build"
    return HOME_PATH / "llama.cpp-omni" / build / "bin" / name


VOICE_REFERENCE = VOICE_DIR / "voice-01.wav"
VOICE_NAMES = {
    "voice-01.wav": "David",
    "voice-02.wav": "Javier",
    "voice-03.wav": "Aitana",
    "voice-04.wav": "Marina",
}


def available_voices() -> list[Path]:
    def natural_key(path):
        return [int(part) if part.isdigit() else part
                for part in re.split(r"(\d+)", path.name.casefold())]

    return sorted((path for path in VOICE_DIR.glob("*")
                   if path.is_file() and path.suffix.casefold() == ".wav"),
                  key=natural_key)


def selected_voice() -> Path | None:
    from .config import load_config

    voices = available_voices()
    name = load_config()["voice_reference"]
    return next((path for path in voices if path.name == name),
                voices[0] if voices else None)


def select_voice(name: str) -> None:
    from .config import load_config, save_config

    if name not in {path.name for path in available_voices()}:
        raise ValueError(f"Voice reference unavailable: {name}")
    config = load_config()
    config["voice_reference"] = name
    save_config(config)


def resolve_voice(name: str) -> Path:
    """Accept only an existing reference from the voice directory."""
    for path in available_voices():
        if path.name == name:
            return path
    raise ValueError(f"Voice reference unavailable: {name}")