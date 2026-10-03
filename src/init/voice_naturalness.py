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
"""Pauses, hesitations and breaths between spoken phrases, never while reading verbatim."""
import os
import random

ENABLED = os.environ.get("ARLO_VOICE_NATURAL", "1") != "0"
FILLER_CHANCE = 0.12
BREATH_CHANCE = 0.18
FILLER_SPACING = 4
BREATH_SPACING = 3
MINIMUM_FILLER_CHARACTERS = 25
LONG_PHRASE_CHARACTERS = 90
LONG_PAUSE_SECONDS = 0.38
FILLER_PAUSE_SECONDS = 0.15
IDLE_PAUSE_SCALE = 0.5

PAUSES = (
    (".…。", (0.28, 0.46)),
    ("!?！？", (0.30, 0.50)),
    (";:；：", (0.20, 0.34)),
    (",，、", (0.10, 0.20)),
)
DEFAULT_PAUSE = (0.06, 0.14)
CLOSERS = " \"'»”’)]"

FILLERS = {
    "es": ("Ehhh...", "Mmm...", "Pues..."),
    "en": ("Uhmmm...", "Ehhh...", "Hmm..."),
    "fr": ("Euh...", "Hmm..."),
    "de": ("Ähm...", "Hmm..."),
    "it": ("Ehm...", "Mmm..."),
    "pt": ("Éhh...", "Hmm..."),
    "ru": ("Эээ...", "Хм..."),
    "ja": ("ええと…", "うーん…"),
    "ko": ("음...", "어..."),
    "zh": ("嗯...", "呃..."),
}


def pause_range(text):
    ending = text.rstrip(CLOSERS)[-1:]
    return next((limits for marks, limits in PAUSES if ending in marks),
                DEFAULT_PAUSE)


class Naturalizer:
    """Plan the silence and embellishment that precede each phrase of one response."""

    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.previous = None
        self.since_filler = 0
        self.since_breath = 0

    def plan(self, text, verbatim, language=None, idle=False):
        """Return the seconds of silence to play first and the text to synthesize."""
        previous, self.previous = self.previous, (text, verbatim)
        if not ENABLED or verbatim or previous is None:
            return 0.0, text
        previous_text, _ = previous
        pause = self.rng.uniform(*pause_range(previous_text))
        spoken = text
        self.since_filler += 1
        self.since_breath += 1
        fillers = FILLERS.get(language or "")
        if (fillers and len(text) >= MINIMUM_FILLER_CHARACTERS
                and self.since_filler > FILLER_SPACING
                and self.rng.random() < FILLER_CHANCE):
            spoken = f"{self.rng.choice(fillers)} {text}"
            pause += FILLER_PAUSE_SECONDS
            self.since_filler = 0
        elif ((len(previous_text) >= LONG_PHRASE_CHARACTERS or pause >= LONG_PAUSE_SECONDS)
                and self.since_breath > BREATH_SPACING
                and self.rng.random() < BREATH_CHANCE):
            spoken = f"[breath] {text}"
            self.since_breath = 0
        return pause * (IDLE_PAUSE_SCALE if idle else 1.0), spoken
