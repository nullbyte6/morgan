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
"""Scored, on-device guesses for how the prompt being typed will continue."""

import json
import os
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

from .config import HOME_PATH

STORE_NAME = "prompt_predictions.json"
MAX_PROMPTS = 400
MAX_PROMPT_LENGTH = 300
MIN_LEARNED = 3
MIN_TYPED = 2
MIN_SCORE = 0.25
MAX_WORDS = 6
HALF_LIFE = 7 * 86400
SEED_COUNT = 2
UNIGRAM_WEIGHT = 0.6
EDGE = ".,;:!?¿¡\"'()[]{}"
SEEDS = (
    "what's the weather like today",
    "open ",
    "play some music",
    "remind me to ",
    "what time is it",
    "search the web for ",
    "tell me a joke",
    "set a timer for ",
    "what's on my agenda today",
    "turn the volume down",
    "write a summary of ",
    "explain how ",
    "qué tiempo hace hoy",
    "abre ",
    "pon algo de música",
    "recuérdame que ",
    "qué hora es",
    "busca en internet ",
    "cuéntame un chiste",
    "pon un temporizador de ",
    "qué tengo hoy en la agenda",
    "baja el volumen",
    "escribe un resumen de ",
    "explícame cómo ",
)


class PromptPredictor:
    """Ranks whole earlier prompts and n-gram word guesses, keeping the best."""

    def __init__(self, path=None):
        self.path = Path(path) if path else HOME_PATH / "json" / STORE_NAME
        self.load()

    def load(self):
        self.prompts = {text: [SEED_COUNT, 0.0] for text in SEEDS}
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))["prompts"]
            for text, count, last in stored:
                if (isinstance(text, str) and len(text) <= MAX_PROMPT_LENGTH
                        and isinstance(count, int) and count > 0
                        and isinstance(last, (int, float))):
                    self.prompts[text] = [count, float(last)]
        except (OSError, ValueError, KeyError, TypeError):
            pass
        self.rebuild()

    def save(self):
        entries = [[text, count, last] for text, (count, last) in self.prompts.items() if last]
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             delete=False) as file:
                temporary = Path(file.name)
                json.dump({"prompts": entries}, file, ensure_ascii=False)
            os.replace(temporary, self.path)
        except OSError:
            pass
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def rebuild(self):
        self.words = Counter()
        self.forms = defaultdict(Counter)
        self.successors = defaultdict(Counter)
        for text, (count, _last) in self.prompts.items():
            self.index(text, count)

    def index(self, text, weight):
        previous = []
        for token in text.split():
            form = token.strip(EDGE)
            if not form:
                continue
            key = form.casefold()
            self.words[key] += weight
            self.forms[key][form] += weight
            for context in {tuple(previous[-2:]), tuple(previous[-1:])}:
                self.successors[context][key] += weight
            previous.append(key)

    def learn(self, text):
        text = " ".join(text.split())
        if not MIN_LEARNED <= len(text) <= MAX_PROMPT_LENGTH:
            return
        now = time.time()
        entry = self.prompts.get(text)
        if entry:
            entry[0] += 1
            entry[1] = now
        else:
            self.prompts[text] = [1, now]
        self.index(text, 1)
        if len(self.prompts) > MAX_PROMPTS:
            ranked = sorted(self.prompts, key=lambda prompt: self.prompts[prompt][0]
                            * 0.5 ** (max(0.0, now - self.prompts[prompt][1]) / HALF_LIFE))
            for prompt in ranked[:len(self.prompts) - MAX_PROMPTS]:
                del self.prompts[prompt]
            self.rebuild()
        self.save()

    def predict(self, text):
        """The text that most likely follows what was typed, or an empty string."""
        body = " ".join(text.split())
        if len(body) < MIN_TYPED:
            return ""
        typed = body + (" " if text[-1:].isspace() else "")
        words, partial = self.split(typed)
        prompt_score, completion = max(
            self.prompt_candidates(typed, time.time()), default=(0.0, ""))
        word_score, word = max(self.word_candidates(words, partial), default=(0.0, ""))
        if max(prompt_score, word_score) < MIN_SCORE:
            return ""
        if prompt_score >= word_score:
            return completion
        return self.phrase(words, partial, word)

    @staticmethod
    def split(typed):
        tokens = typed.split()
        if typed.endswith(" "):
            finished, partial = tokens, ""
        else:
            finished, partial = tokens[:-1], tokens[-1]
            if partial[-1] in EDGE or not partial.lstrip(EDGE):
                partial = None
            else:
                partial = partial.lstrip(EDGE)
        words = [form.casefold() for form in (token.strip(EDGE) for token in finished) if form]
        return words, partial

    def prompt_candidates(self, typed, now):
        length = len(typed.rstrip())
        specificity = length / (length + 3)
        folded = typed.casefold()
        for prompt, (count, last) in self.prompts.items():
            if len(prompt) > len(typed) and prompt[:len(typed)].casefold() == folded:
                frequency = 1 - 1 / (1 + count)
                recency = 0.5 ** (max(0.0, now - last) / HALF_LIFE)
                yield specificity * (0.65 * frequency + 0.35 * recency), prompt[len(typed):]

    def word_candidates(self, words, partial):
        if partial is None:
            return
        folded = partial.casefold()
        if len(words) >= 2:
            contexts = [(tuple(words[-2:]), 1.0), (tuple(words[-1:]), 0.8)]
        else:
            contexts = [(tuple(words), 1.0)]
        for context, weight in contexts:
            counter = self.successors.get(context)
            if counter:
                yield from self.scored(counter, folded, weight, 2)
        if len(folded) >= 2:
            yield from self.scored(self.words, folded, UNIGRAM_WEIGHT, 3)

    @staticmethod
    def scored(counter, partial, weight, smoothing):
        matches = {word: seen for word, seen in counter.items()
                   if len(word) > len(partial) and word.startswith(partial)}
        total = sum(matches.values())
        if not total:
            return
        specificity = len(partial) / (len(partial) + 2) if partial else 0.9
        evidence = total / (total + smoothing)
        for word, seen in matches.items():
            yield weight * specificity * evidence * seen / total, word

    def form(self, key):
        return self.forms[key].most_common(1)[0][0]

    def phrase(self, words, partial, first):
        completion = [self.form(first)[len(partial):]]
        history = [*words, first]
        while len(completion) < MAX_WORDS:
            counter = (self.successors.get(tuple(history[-2:]))
                       or self.successors.get(tuple(history[-1:])))
            if not counter:
                break
            word, seen = counter.most_common(1)[0]
            total = sum(counter.values())
            if total < 2 or seen / total < 0.6 or word == history[-1]:
                break
            completion.append(self.form(word))
            history.append(word)
        return " ".join(completion)


PREDICTOR = PromptPredictor()
