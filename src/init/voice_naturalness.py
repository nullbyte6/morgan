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
"""Pauses, hesitations and breaths between spoken phrases, never while reading verbatim."""
import os
import random
import re

ENABLED = os.environ.get("MORGAN_VOICE_NATURAL", "1") != "0"
FILLER_CHANCE = 0.15
BREATH_CHANCE = 0.18
FILLER_SPACING = 4
COUGH_CHANCE = 0.03
COUGH_SPACING = 12
GIGGLE_CHANCE = 0.25
GIGGLE_SPACING = 6
SOUND_SPACING = 3
SERIOUS_GRAVITY = 0.5
GIGGLE_MAXIMUM_GRAVITY = 0.2
BREATH_SPACING = 3
MINIMUM_FILLER_CHARACTERS = 25
LONG_PHRASE_CHARACTERS = 90
LONG_PAUSE_SECONDS = 0.38
FILLER_PAUSE_SECONDS = 0.15
IDLE_PAUSE_SCALE = 0.5
LAUGH_CUES = re.compile(
    r"\b(?:(?:ha){2,}h?|(?:he){2,}h?|(?:ja){2,}j?|(?:je){2,}j?|(?:ji){2,}j?|(?:hi){2,}h?|lol|lmao|rofl)\b"
    r"|[\U0001F600-\U0001F606\U0001F923]",
    re.IGNORECASE)
LIGHT_CUES = re.compile(
    r"\b(?:funny|joke|hilarious|gracios[oa]s?|chiste|broma|divertid[oa]s?|drôle|lustig|divertente|engraçad[oa])\b",
    re.IGNORECASE)
COUGH_CUES = re.compile(r"\b(?:ahem|coughs?|carraspe\w*)\b|\*coughs?\*", re.IGNORECASE)
SCOFF_CUES = re.compile(r"\b(?:p+f+t*|psh+|tsk|hmph|bah)\b", re.IGNORECASE)

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


def tidy(text):
    text = re.sub(r"\s+([,.;:!?])", r"\1", re.sub(r"\s+", " ", text)).strip()
    return re.sub(r"\.{4,}", "...", re.sub(r"^[\s,;:]+", "", text))


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
        self.since_cough = 0
        self.since_giggle = 0
        self.since_sound = SOUND_SPACING
        self.laughed = False

    def plan(self, text, verbatim, language=None, idle=False, prosody=None):
        """Return the seconds of silence to play first and the text to synthesize."""
        previous, self.previous = self.previous, (text, verbatim)
        self.laughed = False
        energy = prosody.energy if prosody else 0.0
        gravity = prosody.gravity if prosody else 0.0
        if ENABLED and not verbatim:
            text = self._expressions(text, energy, gravity)
        if not ENABLED or verbatim or previous is None:
            return 0.0, text
        previous_text, _ = previous
        pause = self.rng.uniform(*pause_range(previous_text))
        spoken = text
        self.since_filler += 1
        self.since_breath += 1
        self.since_cough += 1
        fillers = FILLERS.get(language or "")
        hesitation = FILLER_CHANCE * (1.0 + 0.4 * max(0.0, gravity) - 0.3 * max(0.0, energy))
        if (fillers and len(text) >= MINIMUM_FILLER_CHARACTERS
                and self.since_filler > FILLER_SPACING
                and self.rng.random() < hesitation):
            spoken = f"{self.rng.choice(fillers)} {text}"
            pause += FILLER_PAUSE_SECONDS
            self.since_filler = 0
        elif ((len(previous_text) >= LONG_PHRASE_CHARACTERS or pause >= LONG_PAUSE_SECONDS)
                and self.since_breath > BREATH_SPACING
                and self.rng.random() < BREATH_CHANCE):
            spoken = f"[breath] {text}"
            self.since_breath = 0
        elif (self.since_cough > COUGH_SPACING and self.since_sound > SOUND_SPACING
                and self.rng.random() < COUGH_CHANCE
                and len(text) >= MINIMUM_FILLER_CHARACTERS):
            spoken = f"[cough] {text}"
            self.since_cough = 0
            self.since_sound = 0
        return pause * (IDLE_PAUSE_SCALE if idle else 1.0), spoken

    def _expressions(self, text, energy, gravity):
        self.since_giggle += 1
        self.since_sound += 1
        free = self.since_sound > SOUND_SPACING
        light = gravity < SERIOUS_GRAVITY
        text, coughs = COUGH_CUES.subn("[cough]" if free else "", text)
        text, scoffs = SCOFF_CUES.subn("[breath]" if free and light else "", text)
        if coughs or scoffs:
            if free:
                self.since_sound = 0
                free = False
            text = tidy(text) or text
        text, laughs = LAUGH_CUES.subn("[laughter]" if free and light else "", text)
        if laughs:
            if free and light:
                self.since_giggle = 0
                self.since_sound = 0
                self.laughed = True
            return tidy(text) or text
        if (free and LIGHT_CUES.search(text) and self.since_giggle > GIGGLE_SPACING
                and gravity < GIGGLE_MAXIMUM_GRAVITY
                and self.rng.random() < GIGGLE_CHANCE * (1.0 + 0.5 * max(0.0, energy))):
            self.since_giggle = 0
            self.since_sound = 0
            self.laughed = True
            return f"{text} [laughter]"
        return text
