#  Copyright (c) 2026 Diego.
#
#  SPDX-License-Identifier: GPL-3.0-or-later
#
#  This file is part of arlo.
"""Word-level subtitle timing derived from a synthesized audio duration."""

from __future__ import annotations

from bisect import bisect_right
import re


_WORD = re.compile(r"\S+")
_PAUSE_WEIGHTS = {
    ",": 2,
    ";": 3,
    ":": 3,
    ".": 4,
    "!": 4,
    "?": 4,
}


def _word_weight(word: str) -> int:
    """Approximate speaking time while accounting for punctuation pauses."""
    spoken = sum(character.isalnum() for character in word)
    pause = max((_PAUSE_WEIGHTS.get(character, 0) for character in word),
                default=0)
    return max(1, spoken) + pause


class WordTimeline:
    """Map playback sample offsets to the word expected at that instant."""

    def __init__(self, text: str, total_samples: int):
        self.words = tuple(_WORD.findall(text))
        self.total_samples = max(0, int(total_samples))
        self._ends = self._build_ends()

    def _build_ends(self) -> tuple[int, ...]:
        if not self.words or self.total_samples <= 0:
            return ()

        weights = tuple(_word_weight(word) for word in self.words)
        total_weight = sum(weights)
        elapsed_weight = 0
        ends = []
        for weight in weights:
            elapsed_weight += weight
            ends.append(self.total_samples * elapsed_weight // total_weight)
        ends[-1] = self.total_samples
        return tuple(ends)

    def word_at(self, sample_offset: int) -> str:
        """Return the current word, clamping offsets to the audio duration."""
        if not self._ends:
            return ""
        offset = min(max(0, int(sample_offset)), self.total_samples - 1)
        index = min(bisect_right(self._ends, offset), len(self.words) - 1)
        return self.words[index]
