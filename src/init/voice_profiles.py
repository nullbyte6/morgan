#  Copyright (c) 2026 Diego.
#
#  SPDX-License-Identifier: GPL-3.0-or-later
#
#  This file is part of morgan.
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
from pathlib import Path

VOICE_DIR = Path(__file__).resolve().parents[1] / "voices"
MODEL_DIR = Path(__file__).resolve().parents[1] / "models"
VOICE_MODEL_NAME = "Fun-CosyVoice3-0.5B"


def _voice_model() -> Path:
    bundled = MODEL_DIR / VOICE_MODEL_NAME
    if (bundled / "cosyvoice3.yaml").is_file():
        return bundled
    from .config import HOME_PATH

    return HOME_PATH / "models" / VOICE_MODEL_NAME


VOICE_MODEL = _voice_model()
VOICE_REFERENCE = VOICE_DIR / "voice-01.wav"
VOICE_REFERENCE_TEXT = "¡Hola! Soy tu asistente personal y estoy aquí para lo que necesites."
VOICE_REFERENCE_LANGUAGE = "spanish"
VOICE_REFERENCE_INSTRUCTION = (f"You are a helpful assistant. "
                               f"Please speak in {VOICE_REFERENCE_LANGUAGE}.<|endofprompt|>")
VOICE_NAMES = {
    "voice-01.wav": "Theo",
    "voice-02.wav": "Leo",
    "voice-03.wav": "Morgan",
    "voice-04.wav": "Nora",
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