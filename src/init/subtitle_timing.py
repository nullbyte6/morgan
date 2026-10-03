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
"""Word-level subtitle timing derived from a synthesized audio duration."""
from __future__ import annotations

from bisect import bisect_right
import re
import threading


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

    def index_at(self, sample_offset: int) -> int | None:
        """Return the current word index for a clamped audio offset."""
        if not self._ends:
            return None
        offset = min(max(0, int(sample_offset)), self.total_samples - 1)
        return min(bisect_right(self._ends, offset), len(self.words) - 1)

    def word_at(self, sample_offset: int) -> str:
        """Return the current word, clamping offsets to the audio duration."""
        index = self.index_at(sample_offset)
        return "" if index is None else self.words[index]

    def text_at(self, sample_offset: int) -> str:
        """Return the phrase revealed through the current spoken word."""
        index = self.index_at(sample_offset)
        return "" if index is None else " ".join(self.words[:index + 1])


class StreamingWordTimeline:
    """Reveal a phrase while its final synthesized duration is still unknown."""

    def __init__(self, text: str, sample_rate: int,
                 characters_per_second: float = 14.0):
        self.text = text
        self.sample_rate = max(1, int(sample_rate))
        self.characters_per_second = max(1.0, float(characters_per_second))
        words = tuple(_WORD.findall(text))
        weight = sum(_word_weight(word) for word in words)
        estimated_samples = round(
            self.sample_rate * weight / self.characters_per_second)
        self._timeline = WordTimeline(text, estimated_samples)
        self._revealed_index = -1
        self._lock = threading.Lock()

    def finalize(self, total_samples: int) -> None:
        """Replace the speaking-rate estimate with the complete audio length."""
        with self._lock:
            self._timeline = WordTimeline(self.text, total_samples)

    def text_at(self, sample_offset: int) -> str:
        """Return monotonically accumulated text at a streamed sample offset."""
        with self._lock:
            index = self._timeline.index_at(sample_offset)
            if index is None:
                return ""
            self._revealed_index = max(self._revealed_index, index)
            return " ".join(
                self._timeline.words[:self._revealed_index + 1])
