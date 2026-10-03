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
"""Subtle, continuous prosody that follows the intent of each phrase without changing the voice."""
import os
import re
from dataclasses import dataclass

ENABLED = os.environ.get("MORGAN_VOICE_PROSODY", "1") != "0"
SMOOTHING = 0.55
MAXIMUM_LEVEL = 1.0
PAUSE_RANGE = (0.8, 1.35)
GAIN_RANGE = (0.86, 1.0)
EMPHASIS_ENERGY = 0.45
EMPHASIS_SPACING = 3
SOFTENING_THRESHOLD = 0.35
LONG_PHRASE_WORDS = 22

LAUGH_SIGNS = re.compile(
    r"\b(?:(?:ha){2,}|(?:he){2,}|(?:ja){2,}|(?:je){2,}|lol|lmao)\b"
    r"|[\U0001F600-\U0001F606\U0001F923]", re.IGNORECASE)
GRAVE_STEMS = re.compile(
    r"\b(?:sorry|apolog|unfortunate|error|fail|problem|danger|careful|warning|serious|"
    r"sad|lament|lo siento|perd[oó]n|desafortunad|peligro|cuidado|advertencia|grave|triste|"
    r"désolé|malheureus|attention|leider|entschuldig|vorsicht|purtroppo|scusa|cuidado|"
    r"infelizmente|desculp)", re.IGNORECASE)
WARM_STEMS = re.compile(
    r"\b(?:thank|great|awesome|perfect|love|glad|happy|congrat|nice|"
    r"gracias|genial|perfecto|encant|feliz|felicidades|"
    r"merci|super|danke|toll|grazie|bellissimo|obrigad|ótimo)", re.IGNORECASE)
LAST_WORD = re.compile(r"([^\W\d_]{3,})([!?.…\s\"'»”’)\]]*)$")


@dataclass(frozen=True)
class Prosody:
    text: str
    pause_scale: float = 1.0
    gain: float = 1.0
    energy: float = 0.0
    gravity: float = 0.0

    @property
    def softness(self):
        return max(0.0, self.gravity) * (1.0 - max(0.0, self.energy))


NEUTRAL_LEVEL = 0.0


def clamp(value, low, high):
    return max(low, min(high, value))


def measure(text):
    """Return the raw energy and gravity a single phrase suggests, each in -1..1."""
    stripped = text.strip()
    words = len(re.findall(r"\w+", stripped))
    exclaimed = "!" in stripped
    questioned = stripped.rstrip("\"'»”’) ").endswith("?")
    trailing_off = "..." in stripped or "…" in stripped
    laughing = bool(LAUGH_SIGNS.search(stripped))
    grave = bool(GRAVE_STEMS.search(stripped))
    warm = bool(WARM_STEMS.search(stripped))
    energy = (0.5 * exclaimed + 0.15 * questioned + 0.25 * laughing + 0.3 * warm
              - 0.25 * trailing_off - 0.2 * grave - 0.12 * (words >= LONG_PHRASE_WORDS))
    gravity = (0.45 * grave + 0.25 * trailing_off + 0.12 * (words >= LONG_PHRASE_WORDS)
               - 0.3 * laughing - 0.2 * warm - 0.15 * exclaimed)
    return (clamp(energy, -MAXIMUM_LEVEL, MAXIMUM_LEVEL),
            clamp(gravity, -MAXIMUM_LEVEL, MAXIMUM_LEVEL))


class ProsodyTracker:
    """Glide between phrases so tone drifts the way a conversation does."""

    def __init__(self):
        self.energy = NEUTRAL_LEVEL
        self.gravity = NEUTRAL_LEVEL
        self.since_emphasis = EMPHASIS_SPACING

    def nudge(self, energy=0.0, gravity=0.0):
        self.energy = clamp(self.energy + energy, -MAXIMUM_LEVEL, MAXIMUM_LEVEL)
        self.gravity = clamp(self.gravity + gravity, -MAXIMUM_LEVEL, MAXIMUM_LEVEL)

    def analyze(self, text, verbatim=False):
        if not ENABLED or verbatim:
            return Prosody(text)
        energy, gravity = measure(text)
        self.energy += SMOOTHING * (energy - self.energy)
        self.gravity += SMOOTHING * (gravity - self.gravity)
        self.since_emphasis += 1
        level = Prosody(text, energy=self.energy, gravity=self.gravity)
        return Prosody(
            self._shape(text, level),
            pause_scale=clamp(1.0 + 0.25 * self.gravity - 0.12 * self.energy, *PAUSE_RANGE),
            gain=clamp(1.0 + 0.04 * self.energy - 0.12 * level.softness, *GAIN_RANGE),
            energy=self.energy, gravity=self.gravity)

    def _shape(self, text, level):
        stripped = text.rstrip()
        if level.softness > SOFTENING_THRESHOLD and stripped.endswith("!"):
            return stripped.rstrip("!") + "."
        if (level.energy > EMPHASIS_ENERGY and self.since_emphasis >= EMPHASIS_SPACING
                and stripped.endswith("!") and " " in stripped and "<" not in stripped):
            emphasized, count = LAST_WORD.subn(r"<strong>\1</strong>\2", stripped, count=1)
            if count:
                self.since_emphasis = 0
                return emphasized
        return text
